import socket
import time
import random
import multiprocessing as mp
import json
import os
import sys

# Configuration constants (will be imported from main)
GATEWAY_PRICE_PORT = 8000
GATEWAY_NEWS_PORT = 8001
MESSAGE_DELIMITER = b'\n'
SYMBOLS = ["AAPL", "MSFT", "GOOGL"]


def price_streamer():
    """Server stream for price data (connected to OrderBook)."""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Use 127.0.0.1 for local communication
    host = '127.0.0.1'

    try:
        server_socket.bind((host, GATEWAY_PRICE_PORT))
        server_socket.listen(1)
        print(f"[GATEWAY|PRICE] Listening for OrderBook on {host}:{GATEWAY_PRICE_PORT}...")
    except Exception as e:
        print(f"[GATEWAY|PRICE] Failed to start server: {e}", file=sys.stderr)
        return

    # Simulate price history for random walk
    current_prices = {sym: random.uniform(100.0, 500.0) for sym in SYMBOLS}

    while True:
        try:
            # Wait for OrderBook to connect
            client_socket, addr = server_socket.accept()
            print(f"[GATEWAY|PRICE] Accepted connection from OrderBook: {addr}")

            while True:
                # 1. Generate new prices (random walk)
                message = ""
                for symbol in SYMBOLS:
                    # Random walk: +/-(0% to 0.1%)
                    change = (random.random() - 0.5) * 0.002
                    current_prices[symbol] *= (1 + change)
                    current_prices[symbol] = round(current_prices[symbol], 2)

                    # Format message: "SYMBOL,PRICE"
                    message += f"{symbol},{current_prices[symbol]:.2f}"

                # 2. Add delimiter and encode
                full_message = message.encode('utf-8') + MESSAGE_DELIMITER

                # 3. Send the message
                client_socket.sendall(full_message)

                # Sleep for 10ms to simulate tick rate
                time.sleep(0.01)

        except ConnectionResetError:
            print("[GATEWAY|PRICE] OrderBook disconnected. Waiting for reconnection...")
            # Close the connection and restart the inner loop to wait for accept()
            if 'client_socket' in locals():
                client_socket.close()
        except Exception as e:
            print(f"[GATEWAY|PRICE] An unexpected error occurred: {e}", file=sys.stderr)
            time.sleep(1)  # Backoff before retrying


def news_streamer():
    """Server stream for news sentiment data (connected to Strategy)."""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    host = '127.0.0.1'

    try:
        server_socket.bind((host, GATEWAY_NEWS_PORT))
        server_socket.listen(1)
        print(f"[GATEWAY|NEWS] Listening for Strategy on {host}:{GATEWAY_NEWS_PORT}...")
    except Exception as e:
        print(f"[GATEWAY|NEWS] Failed to start server: {e}", file=sys.stderr)
        return

    while True:
        try:
            # Wait for Strategy to connect
            client_socket, addr = server_socket.accept()
            print(f"[GATEWAY|NEWS] Accepted connection from Strategy: {addr}")

            while True:
                # 1. Generate random news sentiment (0-100)
                sentiment = random.randint(0, 100)

                # 2. Serialize and frame: JSON int is simple and clear
                message_data = json.dumps(sentiment)
                full_message = message_data.encode('utf-8') + MESSAGE_DELIMITER

                # 3. Send the message
                client_socket.sendall(full_message)

                # News update frequency is slower (e.g., 500ms)
                time.sleep(0.5)

        except ConnectionResetError:
            print("[GATEWAY|NEWS] Strategy disconnected. Waiting for reconnection...")
            if 'client_socket' in locals():
                client_socket.close()
        except Exception as e:
            print(f"[GATEWAY|NEWS] An unexpected error occurred: {e}", file=sys.stderr)
            time.sleep(1)


def run_gateway():
    """Starts the Gateway process with two concurrent streams (price and news)."""
    print(f"[GATEWAY|PID:{os.getpid()}] Starting Gateway...")

    # Use multiprocessing Process for true concurrency (not threads within a single process)
    # However, since the assignment specifies a single Gateway process, we can use threads
    # for the two independent socket streams within the Gateway's main function.

    price_process = mp.Process(target=price_streamer)
    news_process = mp.Process(target=news_streamer)

    price_process.start()
    news_process.start()

    price_process.join()
    news_process.join()


if __name__ == '__main__':
    run_gateway()
