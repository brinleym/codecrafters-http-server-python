from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
import threading
from typing import Union
import socket
import sys

class HTTPStatusCode(IntEnum):
    OK = 200
    NOT_FOUND = 404

@dataclass
class HttpRequest:
    method: str
    target: str
    version: str
    headers: dict[str, str]

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
    
    def read_file(self, filename: str) -> str:
        if self.path == None:
            raise RuntimeError("File mode unsupported: re-run server with --directory <dir>")
        
        file_path = Path(f"/{self.path}/{filename}")
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()

        return content
        
    def handle_request(self, request: HttpRequest) -> HttpResponse:
        target = request.target
        headers = request.headers

        if target == "/":
            return HttpResponse(HTTPStatusCode.OK)
        elif target.startswith("/echo"):
            echo_string = target.split("/")[-1]
            return HttpResponse(HTTPStatusCode.OK, {"Content-Type": "text/plain"}, echo_string)
        elif target.startswith("/files"):
            filename = target.split("/")[-1]
            file_path = Path(f"/{self.root}/{filename}")
            if file_path.exists():
                with open(file_path, "r") as file:
                    content = file.read()
                    return HttpResponse(HTTPStatusCode.OK, {"Content-Type": "application/octet-stream"}, content)
            else:
                return HttpResponse(HTTPStatusCode.NOT_FOUND)
        elif target == "/user-agent":
            user_agent_string = headers["user-agent"]
            return HttpResponse(HTTPStatusCode.OK, {"Content-Type": "text/plain"}, user_agent_string)
        else:
            return HttpResponse(HTTPStatusCode.NOT_FOUND)

    def parse_request(self, raw_bytes: bytes) -> HttpRequest:
        request = raw_bytes.decode()
        lines = request.splitlines()

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

        return HttpRequest(method, target, version, headers)
        
    def handle_conn(self, conn: socket):
        with conn:
            while True: 
                raw_bytes = conn.recv(1024) # Receive data from socket
                
                if not raw_bytes: # Detect closed connection
                    break
            
                request = self.parse_request(raw_bytes)
                response = self.format_response(self.handle_request(request))

                conn.sendall(response)

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
    
    # Setup connection
    server = HttpServer("localhost", 4221, root)
    server.start()

if __name__ == "__main__":
    main()
