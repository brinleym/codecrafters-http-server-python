from dataclasses import dataclass, field
from enum import StrEnum
import gzip
from pathlib import Path
import threading
from typing import Union
import socket
import sys

class HTTPStatusCode(StrEnum):
    OK = "200 OK"
    CREATED = "201 Created"
    NOT_FOUND = "404 Not Found"

class HttpHeaderName(StrEnum):
    ACCEPT_ENCODING = "Accept-Encoding"
    CONNECTION = "Connection"
    CONTENT_ENCODING = "Content-Encoding"
    CONTENT_LENGTH = "Content-Length"
    CONTENT_TYPE = "Content-Type"
    USER_AGENT = "User-Agent"

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
    should_close_connection: bool = False

class HttpServer:
    CRLF = b"\r\n"
    HTTP_VERSION = b"HTTP/1.1"

    def __init__(self, addr: str, port: int, dir: str):
        self.addr = addr
        self.port = port
        self.root = Path(dir)
        self.sock = socket.create_server((self.addr, self.port), reuse_port=True)
        self.sock.listen()

    def format_response(self, response: HttpResponse) -> bytes:
        body = (
            response.body.encode()
            if isinstance(response.body, str)
            else response.body
        )

        response.headers.set(HttpHeaderName.CONTENT_LENGTH, str(len(body)))

        encoded = self.HTTP_VERSION + b" " + response.status.encode() + self.CRLF

        for name, value in response.headers.items():
            encoded += f"{name}: {value}".encode() + self.CRLF

        return encoded + self.CRLF + body
        
    def handle_request(self, request: HttpRequest) -> HttpResponse:
        method = request.method
        target = request.target

        resp_headers = HTTPHeaders()

        should_close_connection = (
            request.headers.has_token(HttpHeaderName.CONNECTION, "close")
        )
        if should_close_connection:
            resp_headers.set(HttpHeaderName.CONNECTION, "close")

        if method == "POST":
            if not request.target.startswith("/files"):
                return HttpResponse(
                    status=HTTPStatusCode.NOT_FOUND, 
                    headers=resp_headers, 
                    should_close_connection=should_close_connection
                )
            
            filename = request.target.split("/")[-1]
            file_path = Path(f"/{self.root}/{filename}")
            
            with open(file_path, "w") as file:
                file.write(request.body)
            
            return HttpResponse(
                status=HTTPStatusCode.CREATED, 
                headers=resp_headers, 
                should_close_connection=should_close_connection
            )

        # method == GET
        if target == "/":
            return HttpResponse(
                status=HTTPStatusCode.OK, 
                headers=resp_headers, 
                should_close_connection=should_close_connection
            )
        
        elif target.startswith("/files"):
            filename = request.target.split("/")[-1]
            file_path = Path(f"/{self.root}/{filename}")

            if not file_path.exists():
                return HttpResponse(
                    status=HTTPStatusCode.NOT_FOUND, 
                    headers=resp_headers, 
                    should_close_connection=should_close_connection
                )

            with open(file_path, "r") as file:
                content = file.read()

            resp_headers.set(HttpHeaderName.CONTENT_TYPE, "application/octet-stream")

            return HttpResponse(
                status=HTTPStatusCode.OK,
                headers=resp_headers,
                body=content,
                should_close_connection=should_close_connection
            )
        
        elif target.startswith("/echo"):
            echo_string = target.split("/")[-1]
            resp_headers.set(HttpHeaderName.CONTENT_TYPE, "text/plain")
            
            if "gzip" in request.accepted_encodings():
                resp_headers.set(HttpHeaderName.CONTENT_ENCODING, "gzip")
                echo_string = gzip.compress(echo_string.encode())

            return HttpResponse(
                status=HTTPStatusCode.OK, 
                headers=resp_headers, 
                body=echo_string, 
                should_close_connection=should_close_connection
            )
        
        elif target == "/user-agent":
            user_agent_string = request.headers.get(HttpHeaderName.USER_AGENT)
            resp_headers.set(HttpHeaderName.CONTENT_TYPE, "text/plain")
            return HttpResponse(
                status=HTTPStatusCode.OK, 
                headers=resp_headers, 
                body=user_agent_string, 
                should_close_connection=should_close_connection
            )
        
        else:
            return HttpResponse(
                status=HTTPStatusCode.NOT_FOUND, 
                headers=resp_headers, 
                should_close_connection=should_close_connection
            )

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
                
                while not b"\r\n\r\n" in raw_bytes:
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

                while len(body_part) < content_length:
                    remaining_bytes = content_length - len(body_part)
                    
                    chunk = conn.recv(min(4096, remaining_bytes))
                    if not chunk:
                        break
                   
                    body_part += chunk
            
                request = self.parse_request(headers_part, body_part)
                response = self.handle_request(request)
                response_bytes = self.format_response(response)
                
                conn.sendall(response_bytes)
                
                if response.should_close_connection:
                    conn.close()

    def start(self):
        with self.sock:
            while True:
                conn, _ = self.sock.accept()
                thread = threading.Thread(target=self.handle_conn, args=(conn,), daemon=True)
                thread.start()

def main():
    root = "/"
    # Parse arguments
    if len(sys.argv) > 2:
        arg1, arg2 = sys.argv[1], sys.argv[2]
        if arg1 != "--directory":
            raise ValueError("Unsupported argument")
        root = arg2
    
    # Setup HTTP server
    server = HttpServer("localhost", 4221, root)
    server.start()

if __name__ == "__main__":
    main()
