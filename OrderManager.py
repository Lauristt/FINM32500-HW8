import socket
import time
import os
import sys
import json
import multiprocessing as mp

# Configuration constants
ORDER_MANAGER_PORT = 8002
MESSAGE_DELIMITER = b'\n'
HOST = '127.0.0.1'

# Global buffer to handle fragmented messages across socket reads
recv_buffer = b''


def receive_framed_message(sock: socket.socket) -> str:
    """
    Receives bytes from the socket and returns a single framed message.
    Handles message fragmentation and buffering.
    """
    global recv_buffer

    while True:
        # Try to find a complete message in the existing buffer
        delimiter_pos = recv_buffer.find(MESSAGE_DELIMITER)
        if delimiter_pos != -1:
            # Found a complete message
            message = recv_buffer[:delimiter_pos]
            recv_buffer = recv_buffer[delimiter_pos + len(MESSAGE_DELIMITER):]
            return message.decode('utf-8')

        # If no complete message, read more data
        chunk = sock.recv(4096)
        if not chunk:
            # Connection closed
            raise ConnectionResetError("Strategy client closed the connection.")

        recv_buffer += chunk


def run_ordermanager():
    """
    Acts as a TCP server receiving Order objects from Strategy clients.
    """
    pid = os.getpid()
    print(f"[OM|PID:{pid}] Starting OrderManager...")

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((HOST, ORDER_MANAGER_PORT))
        server_socket.listen(5)  # Allow multiple strategy clients (if we scale up)
        print(f"[OM] Listening for Strategy clients on {HOST}:{ORDER_MANAGER_PORT}...")
    except Exception as e:
        print(f"[OM] Failed to start server: {e}", file=sys.stderr)
        return

    while True:
        try:
            # Wait for Strategy to connect
            client_socket, addr = server_socket.accept()
            print(f"[OM] Accepted connection from Strategy: {addr}")

            global recv_buffer
            recv_buffer = b''  # Clear buffer on fresh connection

            while True:
                raw_order = receive_framed_message(client_socket)
                order = json.loads(raw_order)
                print(
                    f"[OM|EXECUTED] Order {order['order_id']:<4}: {order['side']:<4} {order['quantity']:<2} {order['symbol']:<5} @ {order['price']:.2f} (TS: {order['timestamp']:.2f})")

        except ConnectionResetError as e:
            print(f"[OM] Strategy client disconnected: {e}. Waiting for a new connection...")
            if 'client_socket' in locals():
                client_socket.close()
        except json.JSONDecodeError:
            print(f"[OM] Serialization Error: Received invalid JSON.", file=sys.stderr)
        except Exception as e:
            print(f"[OM] An unexpected error occurred: {e}", file=sys.stderr)
            time.sleep(1)