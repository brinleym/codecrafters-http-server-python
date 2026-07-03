from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
import gzip
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
    accepted_encodings: list[str]

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
        
    def handle_request(self, request: HttpRequest) -> tuple[HttpResponse, bool]:
        method = request.method
        target = request.target
        headers = request.headers
        accepted_encodings = request.accepted_encodings

        resp_headers = {}
        should_close_connection = (
            headers.get("connection", "") == "close"
        )

        if should_close_connection:
            resp_headers["connection"] = "close"

        if method == "POST":
            if not request.target.startswith("/files"):
                return HttpResponse(HTTPStatusCode.NOT_FOUND, resp_headers), should_close_connection
            
            filename = request.target.split("/")[-1]
            file_path = Path(f"/{self.root}/{filename}")
            with open(file_path, "w") as file:
                file.write(request.body)
            
            return HttpResponse(HTTPStatusCode.CREATED, resp_headers), should_close_connection

        # method == GET
        if target == "/":
            return HttpResponse(HTTPStatusCode.OK, resp_headers), should_close_connection
        
        elif target.startswith("/files"):
            filename = request.target.split("/")[-1]
            file_path = Path(f"/{self.root}/{filename}")

            if not file_path.exists():
                return HttpResponse(HTTPStatusCode.NOT_FOUND, resp_headers), should_close_connection

            with open(file_path, "r") as file:
                content = file.read()

            resp_headers["content-type"] = "application/octet-stream"

            return HttpResponse(
                HTTPStatusCode.OK,
                resp_headers,
                content,
            ), should_close_connection
        
        elif target.startswith("/echo"):
            echo_string = target.split("/")[-1]
            resp_headers["content-type"] = "text/plain"
            
            if "gzip" in accepted_encodings:
                resp_headers["content-encoding"] = "gzip"
                echo_string = gzip.compress(echo_string.encode())

            return HttpResponse(HTTPStatusCode.OK, resp_headers, echo_string), should_close_connection
        
        elif target == "/user-agent":
            user_agent_string = headers["user-agent"]
            resp_headers["content-type"] = "text/plain"
            return HttpResponse(HTTPStatusCode.OK, resp_headers, user_agent_string), should_close_connection
        
        else:
            return HttpResponse(HTTPStatusCode.NOT_FOUND, resp_headers), should_close_connection

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

            header, value = line.split(":", maxsplit=1)
            headers[header.strip().lower()] = value.strip()

        accepted_encodings = []
        if "accept-encoding" in headers:
            accepted_encodings = [encoding.strip() for encoding in value.split(",")]

        return HttpRequest(method, target, version, headers, body_part.decode(), accepted_encodings)
        
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
                response, should_close_connection = self.handle_request(request)
                response_bytes = self.format_response(response)
                conn.sendall(response_bytes)
                if should_close_connection:
                    conn.close()

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
