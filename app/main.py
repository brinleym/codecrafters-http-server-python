import socket
from urllib.parse import urlsplit


def main():
    OK = b"HTTP/1.1 200 OK\r\n\r\n"
    NOT_FOUND = b"HTTP/1.1 404 Not Found\r\n\r\n"
    
    # Setup connection
    server_socket = socket.create_server(("localhost", 4221), reuse_port=True)
    conn, _ = server_socket.accept() # wait for client

    # Receive + parse request
    bytes = conn.recv(1024)
    data = bytes.decode()
    parts = data.split(" ")
    target_url = parts[1]
    path = urlsplit(target_url).path

    # Handle request
    resp = OK
    if len(path) > 0: #
        resp = NOT_FOUND

    conn.sendall(resp)
    conn.close()

if __name__ == "__main__":
    main()
