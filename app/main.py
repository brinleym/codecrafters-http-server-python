from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
import threading
from typing import Union
import socket
import sys

class HTTPStatusCode(IntEnum):
    OK = 200
    CREATED = 201
    NOT_FOUND = 404

@dataclass
class HttpRequest:
    method: str
    target: str
    version: str
    headers: dict[str, str]
    body: str

@dataclass
class HttpResponse:
    status: HTTPStatusCode
    headers: dict[str, str] = field(default_factory=dict)
    body: Union[str, bytes] = field(default_factory=str)

class HttpServer:
    CRLF = b"\r\n"
    HTTP_VERSION = b"HTTP/1.1"

    def __init__(self, addr: str, port: int, dir: str):
        self.addr = addr
        self.port = port
        self.root = Path(dir) if dir != None else None
        self.sock = socket.create_server((self.addr, self.port), reuse_port=True)
        self.sock.listen()

    def format_status_code(self, status_code: HTTPStatusCode) -> bytes:
        if status_code == HTTPStatusCode.OK:
            return b"200 OK"
        elif status_code == HTTPStatusCode.CREATED:
            return b"201 Created"
        elif status_code == HTTPStatusCode.NOT_FOUND:
            return b"404 Not Found"
        else:
            raise ValueError("Unsupported status code")

    def format_response(self, response: HttpResponse) -> bytes:
        body = (
            response.body.encode()
            if isinstance(response.body, str)
            else response.body
        )

        headers = {
            **response.headers,
            "Content-Length": str(len(body)),
        }

        encoded = self.HTTP_VERSION + b" " + self.format_status_code(response.status) + self.CRLF

        for key, value in headers.items():
            encoded += f"{key}: {value}".encode() + self.CRLF

        return encoded + self.CRLF + body
    
    def handle_file_get(self, request: HttpRequest) -> HttpResponse:
        filename = request.target.split("/")[-1]
        file_path = Path(f"/{self.root}/{filename}")

        if not file_path.exists():
            return HttpResponse(HTTPStatusCode.NOT_FOUND)

        with open(file_path, "r") as file:
            content = file.read()

        return HttpResponse(
            HTTPStatusCode.OK,
            {"Content-Type": "application/octet-stream"},
            content,
        )
    
    def handle_post(self, request: HttpRequest) -> HttpResponse:
        if not request.target.startswith("/files"):
            return HttpResponse(HTTPStatusCode.NOT_FOUND)
        
        filename = request.target.split("/")[-1]
        file_path = Path(f"/{self.root}/{filename}")
        with open(file_path, "w") as file:
            file.write(request.body)
        
        return HttpResponse(HTTPStatusCode.CREATED)
        
    def handle_request(self, request: HttpRequest) -> HttpResponse:
        method = request.method
        target = request.target
        headers = request.headers

        if method == "POST":
            return self.handle_post(request)

        # method == GET
        if target == "/":
            return HttpResponse(HTTPStatusCode.OK)
        elif target.startswith("/files"):
            return self.handle_file_get(request)
        elif target.startswith("/echo"):
            echo_string = target.split("/")[-1]
            resp_headers = {"Content-Type": "text/plain"}
            if "accept-encoding" in headers and headers["accept-encoding"] == "gzip":
                resp_headers["Content-Encoding"] = "gzip"

            return HttpResponse(HTTPStatusCode.OK, resp_headers, echo_string)
        elif target == "/user-agent":
            user_agent_string = headers["user-agent"]
            return HttpResponse(HTTPStatusCode.OK, {"Content-Type": "text/plain"}, user_agent_string)
        else:
            return HttpResponse(HTTPStatusCode.NOT_FOUND)

    def parse_request(self, headers_part: bytes, body_part: bytes) -> HttpRequest:
        headers_text = headers_part.decode()
        lines = headers_text.splitlines()

        # request line
        request_line = lines[0]
        method, target, version = request_line.split()

        # headers
        headers = {}
        for line in lines[1:]:
            if not line:
                break

            header_type, value = line.split(":", maxsplit=1)
            headers[header_type.strip().lower()] = value.strip()

        return HttpRequest(method, target, version, headers, body_part.decode())
        
    def handle_conn(self, conn: socket):
        with conn:
            while True: 
                raw_bytes = b""
                
                while b"\r\n\r\n" not in raw_bytes:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    
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

    def start(self):
        with self.sock:
            while True:
                conn, _ = self.sock.accept()
                thread = threading.Thread(target=self.handle_conn, args=(conn,), daemon=True)
                thread.start()

def main():
    root = None
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
