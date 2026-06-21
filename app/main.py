from dataclasses import dataclass
import socket

@dataclass
class HttpRequest:
    method: str
    target: str
    version: str
    headers: dict[str, str]

def parse_request(raw_bytes: bytes) -> HttpRequest:
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

def route_request(request: HttpRequest) -> bytes:
    target = request.target
    headers = request.headers

    if target == "/":
        return b"HTTP/1.1 200 OK\r\n\r\n"
    elif target.startswith("/echo"):
        content = target.split("/")[-1].encode()
        content_length = str(len(content)).encode()
        return b"HTTP/1.1 200 OK\r\n" + b"Content-Type: text/plain\r\n" + b"Content-Length:" + content_length + b"\r\n\r\n" + content
    elif target == "/user-agent":
        user_agent = headers["user-agent"].encode()
        user_agent_length = str(len(user_agent)).encode()
        return b"HTTP/1.1 200 OK\r\n" + b"Content-Type: text/plain\r\n" + b"Content-Length:" + user_agent_length + b"\r\n\r\n" + user_agent
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
