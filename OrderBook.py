import socket
import time
import os
import sys
import multiprocessing as mp
from typing import Optional
from shared_memory_utils import SharedPriceBook, SocketStreamClosed, close_shared_price_book

# Configuration constants
GATEWAY_PRICE_PORT = 8000
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
        try:
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
                raise SocketStreamClosed("Gateway price stream closed.")

            recv_buffer += chunk

        except BlockingIOError:
            # Non-blocking socket read (should not happen with blocking sockets by default)
            time.sleep(0.001)
        except Exception as e:
            raise SocketStreamClosed(f"Socket error: {e}")


def run_orderbook(shm_name: str, shm_lock: mp.Lock, symbols: list):
    """
    Connects to the Gateway price stream and updates the SharedPriceBook.
    """
    pid = os.getpid()
    print(f"[ORDERBOOK|PID:{pid}] Starting OrderBook...")
    shm_book: Optional[SharedPriceBook] = None
    try:
        shm_book = SharedPriceBook(symbols=symbols, shm_name=shm_name, lock=shm_lock, create=False)
    except FileNotFoundError:
        print(f"[{pid}] Fatal: Shared memory '{shm_name}' not found. Exiting.", file=sys.stderr)
        return

    while True:
        try:
            # Create a new socket for each attempt (handles reconnection)
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            print(f"[{pid}] Attempting to connect to Gateway Price Stream at {HOST}:{GATEWAY_PRICE_PORT}...")
            client_socket.connect((HOST, GATEWAY_PRICE_PORT))
            print(f"[{pid}] Connected to Gateway Price Stream.")

            # 3. Message reception loop
            global recv_buffer
            recv_buffer = b''  # Clear buffer on fresh connection

            while True:
                # Receive one framed message
                raw_message = receive_framed_message(client_socket)

                # Parse the message (e.g., "AAPL,172.53MSFT,325.20")
                if not raw_message:
                    continue

                # The message is a concatenation of SYMBOL,PRICE pairs
                # We can split by symbol names to parse it, but a simpler way is
                # to process it as a list of "SYMBOL,PRICE" strings.

                # Strip the last delimiter if present, although the receiver handles framing
                message_parts = raw_message.split(' ')  # Using space as an implied separator for multiple symbols

                # In gateway.py, I concatenated symbols: "AAPL,P1MSFT,P2GOOGL,P3"
                # A simple split by symbol name is easiest to maintain consistency.

                parsed_ticks = {}
                try:
                    # Example parsing for "AAPL,172.53MSFT,325.20GOOGL,1250.00"

                    # Split string into SYMBOL,PRICE segments
                    # This relies on the fixed symbols, a better protocol would use a separator.
                    # Since the Gateway implementation does not use a separator between symbols,
                    # we will manually parse based on expected symbol lengths.

                    # Simple (but slightly fragile) parsing:
                    for symbol in symbols:
                        if symbol in raw_message:
                            start_index = raw_message.find(symbol) + len(symbol) + 1  # Find symbol + comma

                            # Find the end of the price (until the next symbol name or end of string)
                            end_index = len(raw_message)

                            # Determine end of price value (either end of string or start of next symbol name)
                            # Assuming symbols are 4-5 chars for standard stocks
                            for next_symbol in symbols:
                                if next_symbol != symbol and raw_message.find(next_symbol, start_index) != -1:
                                    end_index = min(end_index, raw_message.find(next_symbol, start_index))

                            price_str = raw_message[start_index:end_index]

                            price = float(price_str.strip())

                            # 4. Update shared memory
                            shm_book.update(symbol, price)
                            parsed_ticks[symbol] = price

                    # print(f"[{pid}] Updated SHM: {parsed_ticks}")

                except ValueError as ve:
                    # Catch cases where the price conversion fails
                    print(f"[{pid}] Parsing Error: Invalid price data in '{raw_message}'. {ve}", file=sys.stderr)

                except Exception as e:
                    print(f"[{pid}] General Parsing Error: {e}", file=sys.stderr)

        except SocketStreamClosed as e:
            print(f"[{pid}] Connection Error: {e}")
            client_socket.close()
            time.sleep(2)  # Wait before attempting reconnection
        except ConnectionRefusedError:
            print(f"[{pid}] Connection Refused. Gateway not running or port wrong. Retrying in 2s...")
            time.sleep(2)
        except Exception as e:
            print(f"[{pid}] Unexpected Error: {e}", file=sys.stderr)
            time.sleep(2)

    # Cleanup (not strictly reached, but good practice)
    close_shared_price_book(shm_book)


if __name__ == '__main__':
    # This block is for independent testing only, main.py handles orchestration
    print("Run via main.py for full context.")