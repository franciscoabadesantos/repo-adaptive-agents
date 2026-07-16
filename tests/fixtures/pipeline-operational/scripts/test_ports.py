import socket

def check_port(host: str, port: int) -> bool:
    return socket.create_connection((host, port), timeout=2) is not None
