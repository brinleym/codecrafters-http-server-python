import socket


def main():
    OK_RESP = "HTTP/1.1 200 OK\r\n\r\n"
    server_socket = socket.create_server(("localhost", 4221), reuse_port=True)
    server_socket.accept() # wait for client
    server_socket.send(OK_RESP)


if __name__ == "__main__":
    main()
