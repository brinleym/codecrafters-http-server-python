from dataclasses import dataclass
import socket

@dataclass
class HttpRequest:
    method: str
    target: str
    version: str

def parse_request(raw_bytes: bytes) -> HttpRequest:
    request = raw_bytes.decode()
    request_line = request.splitlines()[0]
    method, target, version = request_line.split()
    return HttpRequest(method, target, version)

def route_request(request: HttpRequest) -> bytes:
    target = request.target

    if target == "/":
        return b"HTTP/1.1 200 OK\r\n\r\n"
    elif target.startswith("/echo"):
        content = target.split("/")[-1].encode()
        content_length = str(len(content)).encode()
        return b"HTTP/1.1 200 OK\r\n" + b"Content-Type: text/plain\r\n" + b"Content-Length:" + content_length + b"\r\n\r\n" + content
    else:
        return b"HTTP/1.1 404 Not Found\r\n\r\n"

def main():
    # Setup connection
    server_socket = socket.create_server(("localhost", 4221), reuse_port=True)
    conn, _ = server_socket.accept() # wait for client

    # Receive + parse request
    raw_bytes = conn.recv(1024)
    request = parse_request(raw_bytes)

    # Handle request
    resp = route_request(request)

    conn.sendall(resp)
    conn.close()

if __name__ == "__main__":
    main()
