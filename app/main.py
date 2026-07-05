from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
import gzip
from pathlib import Path
import threading
from typing import Union
import socket
import sys

CRLF = b"\r\n"
HTTP_VERSION = b"HTTP/1.1"

class HTTPStatusCode(StrEnum):
    OK = "200 OK"
    CREATED = "201 Created"
    NOT_FOUND = "404 Not Found"

class HttpHeaderName(StrEnum):
    ACCEPT_ENCODING = "accept-encoding"
    CONNECTION = "connection"
    CONTENT_ENCODING = "content-encoding"
    CONTENT_LENGTH = "content-length"
    CONTENT_TYPE = "content-type"
    USER_AGENT = "user-agent"

class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"

@dataclass
class HTTPHeaders:
    headers: dict[str, str] = field(default_factory=dict)

    def parse(self, text: str) -> None:
        for line in text:
            if not line:
                break

            name, value = line.split(":", maxsplit=1)
            self.headers[name.strip().lower()] = value.strip()

    def contains(self, name: str) -> bool:
        return self._normalize(name) in self.headers
    
    def has_token(self, name: str, value: str) -> bool:
        return self.headers.get(self._normalize(name)) == value
    
    def get(self, name: str) -> str:
        return self.headers.get(self._normalize(name))
    
    def tokens(self, name: str) -> list[str]:
        value = self.headers.get(self._normalize(name))
        return [self._normalize(tok) for tok in value.split(",")] if value != None else []
    
    def set(self, name: str, value: str) -> None:
        self.headers[self._normalize(name)] = self._normalize(value)

    def remove(self, name: str) -> None:
        del self.headers[self._normalize(name)]

    def clear(self) -> None:
        self.headers.clear()

    def items(self) -> list[tuple[str, str]]:
        return [(name, value) for name, value in self.headers.items()]
    
    def _normalize(self, text: str) -> str:
        return text.strip().lower()

@dataclass
class HttpRequest:
    method: str
    target: str
    version: str
    headers: HTTPHeaders
    body: str

    def accepted_encodings(self) -> list[str]:
        return self.headers.tokens(HttpHeaderName.ACCEPT_ENCODING)

@dataclass
class HttpResponse:
    status: HTTPStatusCode
    headers: HTTPHeaders
    body: Union[str, bytes] = field(default_factory=str)

    def serialize(self) -> bytes:
        body = (
            self.body.encode()
            if isinstance(self.body, str)
            else self.body
        )

        self.headers.set(HttpHeaderName.CONTENT_LENGTH, str(len(body)))

        headers = HTTP_VERSION + b" " + self.status.encode() + CRLF

        for name, value in self.headers.items():
            headers += f"{name}: {value}".encode() + CRLF

        return headers + CRLF + body
    
@dataclass
class HttpServerConfig:
    root: str = ""
    
class HttpRequestHandler(ABC):
    def __init__(self, config: HttpServerConfig):
        self.config = config

    @abstractmethod
    def handle(self, request: HttpRequest) -> HttpResponse:
        pass

    def add_common_headers(self, request: HttpRequest) -> HTTPHeaders:
        resp_headers = HTTPHeaders()

        should_close_connection = (
            request.headers.has_token(HttpHeaderName.CONNECTION, "close")
        )
        if should_close_connection:
            resp_headers.set(HttpHeaderName.CONNECTION, "close")

        return resp_headers


class RootHandler(HttpRequestHandler):
    def __init__(self, config: HttpServerConfig):
        super().__init__(config)

    def handle(self, request: HttpRequest) -> HttpResponse:
        resp_headers = self.add_common_headers(request)

        return HttpResponse(
            status=HTTPStatusCode.OK, 
            headers=resp_headers
        )
    
class FileGetHandler(HttpRequestHandler):
    def __init__(self, config: HttpServerConfig):
        super().__init__(config)

    def handle(self, request: HttpRequest) -> HttpResponse:
        resp_headers = self.add_common_headers(request)

        filename = request.target.split("/")[-1]
        file_path = Path(f"{self.config.root}/{filename}")

        if not file_path.exists():
            return HttpResponse(
                status=HTTPStatusCode.NOT_FOUND, 
                headers=resp_headers
            )

        with open(file_path, "r") as file:
            content = file.read()

        resp_headers.set(HttpHeaderName.CONTENT_TYPE, "application/octet-stream")

        return HttpResponse(
            status=HTTPStatusCode.OK,
            headers=resp_headers,
            body=content
        )
    
class FilePostHandler(HttpRequestHandler):
    def __init__(self, config: HttpServerConfig):
        super().__init__(config)

    def handle(self, request: HttpRequest) -> HttpResponse:
        resp_headers = self.add_common_headers(request)

        filename = request.target.split("/")[-1]
        file_path = Path(f"{self.config.root}/{filename}")
        
        with open(file_path, "w") as file:
            file.write(request.body)
        
        return HttpResponse(
            status=HTTPStatusCode.CREATED, 
            headers=resp_headers
        )
    
class EchoHandler(HttpRequestHandler):
    def __init__(self, config: HttpServerConfig):
        super().__init__(config)

    def handle(self, request: HttpRequest) -> HttpResponse:
        resp_headers = self.add_common_headers(request)

        echo_string = request.target.split("/")[-1]
        resp_headers.set(HttpHeaderName.CONTENT_TYPE, "text/plain")
        
        if "gzip" in request.accepted_encodings():
            resp_headers.set(HttpHeaderName.CONTENT_ENCODING, "gzip")
            echo_string = gzip.compress(echo_string.encode())

        return HttpResponse(
            status=HTTPStatusCode.OK, 
            headers=resp_headers, 
            body=echo_string
        )
    
class UserAgentHandler(HttpRequestHandler):
    def __init__(self, config: HttpServerConfig):
        super().__init__(config)

    def handle(self, request: HttpRequest) -> HttpResponse:
        resp_headers = self.add_common_headers(request)
        
        user_agent_string = request.headers.get(HttpHeaderName.USER_AGENT)
        resp_headers.set(HttpHeaderName.CONTENT_TYPE, "text/plain")
        return HttpResponse(
            status=HTTPStatusCode.OK, 
            headers=resp_headers, 
            body=user_agent_string
        )
    
class NotFoundHandler(HttpRequestHandler):
    def __init__(self, config: HttpServerConfig):
        super().__init__(config)

    def handle(self, request: HttpRequest) -> HttpResponse:
        resp_headers = self.add_common_headers(request)

        return HttpResponse(
            status=HTTPStatusCode.NOT_FOUND, 
            headers=resp_headers
        )
    
class RequestHandlerFactory:
    def __init__(self):
        pass

    def create(self, request: HttpRequest, config: HttpServerConfig) -> HttpRequestHandler:
        if request.target == "/":
            return RootHandler(config)
        elif request.target.startswith("/files") and request.method == HttpMethod.GET:
            return FileGetHandler(config)
        elif request.target.startswith("/files") and request.method == HttpMethod.POST:
            return FilePostHandler(config)
        elif request.target.startswith("/echo"):
            return EchoHandler(config)
        elif request.target == "/user-agent":
            return UserAgentHandler(config)
        else:
            return NotFoundHandler(config)

class HttpServer:
    def __init__(self, addr: str, port: int, config: HttpServerConfig):
        self.addr = addr
        self.port = port
        self.config = config
        self.request_handler_factory = RequestHandlerFactory()
        self.sock = socket.create_server((self.addr, self.port), reuse_port=True) # bind socket to (addr, port)

    def parse_request(self, headers_part: bytes, body_part: bytes) -> HttpRequest:
        headers_text = headers_part.decode()
        header_lines = headers_text.splitlines()

        # request line
        request_line = header_lines[0]
        method, target, version = request_line.split()

        # headers
        headers = HTTPHeaders()
        headers.parse(header_lines[1:])

        return HttpRequest(method, target, version, headers, body_part.decode())
        
    def handle_conn(self, conn: socket):
        with conn:
            while True: 
                raw_bytes = b""
                
                while not b"\r\n\r\n" in raw_bytes: # read headers
                    chunk = conn.recv(4096)
                    if not chunk: # connection closed
                        return
                    
                    raw_bytes += chunk

                headers_part, body_part = raw_bytes.split(b"\r\n\r\n", maxsplit=1)
                headers_text = headers_part.decode()

                content_length = 0
                for line in headers_text.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":")[1].strip())
                        break

                while len(body_part) < content_length: # read body
                    remaining_bytes = content_length - len(body_part)
                    
                    chunk = conn.recv(min(4096, remaining_bytes))
                    if not chunk:
                        break
                   
                    body_part += chunk
            
                request = self.parse_request(headers_part, body_part)
                request_handler = self.request_handler_factory.create(request, self.config)
                response = request_handler.handle(request)
                
                conn.sendall(response.serialize())
                
                if response.headers.has_token(HttpHeaderName.CONNECTION, "close"):
                    break # close connection

    def start(self):
        self.sock.listen()
        with self.sock:
            while True:
                conn, _ = self.sock.accept()
                thread = threading.Thread(target=self.handle_conn, args=(conn,), daemon=True)
                thread.start()

def main():
    root = ""
    # Parse arguments
    if len(sys.argv) > 2:
        arg1, arg2 = sys.argv[1], sys.argv[2]
        if arg1 != "--directory":
            raise ValueError("Unsupported argument")
        root = arg2
    
    # Setup HTTP server
    config = HttpServerConfig(root=Path(root))
    server = HttpServer(addr="localhost", port=4221, config=config)
    server.start()

if __name__ == "__main__":
    main()
