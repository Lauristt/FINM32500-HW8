import socket
import time
import os
import sys
import json
import numpy as np
import multiprocessing as mp
from collections import deque
from typing import Optional
from shared_memory_utils import SharedPriceBook, SocketStreamClosed, close_shared_price_book

# Configuration constants
GATEWAY_NEWS_PORT = 8001
ORDER_MANAGER_PORT = 8002
MESSAGE_DELIMITER = b'\n'
HOST = '127.0.0.1'

# Strategy parameters
BULLISH_THRESHOLD = 70
BEARISH_THRESHOLD = 30
SHORT_WINDOW = 5  # For moving average
LONG_WINDOW = 20  # For moving average
MAX_HISTORY = LONG_WINDOW * 2  # Keep twice the long window of history


# State object for the strategy
class StrategyState:
    def __init__(self, symbols):
        self.price_history = {sym: deque(maxlen=MAX_HISTORY) for sym in symbols}
        self.position = {sym: 'NONE' for sym in symbols}  # NONE, LONG, or SHORT
        self.order_counter = 1

    def update_price_history(self, ticks):
        for sym, price in ticks.items():
            if price > 0:
                self.price_history[sym].append(price)

    def get_ma(self, symbol, window):
        history = list(self.price_history[symbol])
        if len(history) < window:
            return None
        return np.mean(history[-window:])


# Global buffer for news stream
news_recv_buffer = b''


def receive_framed_news_message(sock: socket.socket) -> str:
    """Receives framed message from the news stream."""
    global news_recv_buffer

    while True:
        try:
            delimiter_pos = news_recv_buffer.find(MESSAGE_DELIMITER)
            if delimiter_pos != -1:
                message = news_recv_buffer[:delimiter_pos]
                news_recv_buffer = news_recv_buffer[delimiter_pos + len(MESSAGE_DELIMITER):]
                return message.decode('utf-8')

            chunk = sock.recv(4096)
            if not chunk:
                raise SocketStreamClosed("Gateway news stream closed.")

            news_recv_buffer += chunk

        except Exception as e:
            raise SocketStreamClosed(f"Socket error: {e}")


def _send_order(sock: socket.socket, order: dict):
    """Helper to serialize and send an order to OrderManager."""
    try:
        message_data = json.dumps(order)
        full_message = message_data.encode('utf-8') + MESSAGE_DELIMITER
        sock.sendall(full_message)
        print(
            f"[STRATEGY|SENT] Order {order['order_id']}: {order['side']} {order['quantity']} {order['symbol']} @ {order['price']:.2f}")
    except Exception as e:
        print(f"[STRATEGY|ERROR] Failed to send order {order['order_id']} to OrderManager: {e}", file=sys.stderr)


def run_strategy(shm_name: str, shm_lock: mp.Lock, symbols: list):
    """
    Connects to the Gateway news stream and OrderManager.
    Reads shared memory and generates trading signals.
    """
    pid = os.getpid()
    print(f"[STRATEGY|PID:{pid}] Starting Strategy...")

    # 1. Attach to shared memory
    shm_book: Optional[SharedPriceBook] = None
    try:
        shm_book = SharedPriceBook(symbols=symbols, shm_name=shm_name, lock=shm_lock, create=False)
    except FileNotFoundError:
        print(f"[{pid}] Fatal: Shared memory '{shm_name}' not found. Exiting.", file=sys.stderr)
        return

    # Initialize Strategy State
    state = StrategyState(symbols)

    # OrderManager socket is created once and reused
    om_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    om_connected = False

    # 2. Main loop for news stream connection/reconnection
    while True:
        # Connect to OrderManager if not connected
        if not om_connected:
            try:
                print(f"[{pid}] Attempting to connect to OrderManager at {HOST}:{ORDER_MANAGER_PORT}...")
                om_socket.connect((HOST, ORDER_MANAGER_PORT))
                om_connected = True
                print(f"[{pid}] Connected to OrderManager.")
            except ConnectionRefusedError:
                print(f"[{pid}] OrderManager Refused. Retrying in 1s...")
                time.sleep(1)
                continue
            except Exception as e:
                print(f"[{pid}] OM Connect Error: {e}. Retrying in 1s...", file=sys.stderr)
                time.sleep(1)
                continue

        # Connect to Gateway News Stream
        news_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            print(f"[{pid}] Attempting to connect to Gateway News Stream at {HOST}:{GATEWAY_NEWS_PORT}...")
            news_socket.connect((HOST, GATEWAY_NEWS_PORT))
            print(f"[{pid}] Connected to Gateway News Stream.")

            global news_recv_buffer
            news_recv_buffer = b''

            # 3. Strategy execution loop
            while True:
                # --- A. Receive News Tick (Driving factor) ---
                try:
                    raw_news = receive_framed_news_message(news_socket)
                    sentiment = json.loads(raw_news)
                except SocketStreamClosed:
                    raise SocketStreamClosed("News stream failed. Reconnecting...")

                # --- B. Read Market Data from Shared Memory ---
                current_ticks = shm_book.read_all()
                state.update_price_history(current_ticks)

                # --- C. Determine Trading Signal ---
                for symbol, current_price in current_ticks.items():
                    if current_price == 0.0:
                        continue  # Skip if price hasn't been initialized

                    # 1. Price-based Signal (MA Crossover)
                    short_ma = state.get_ma(symbol, SHORT_WINDOW)
                    long_ma = state.get_ma(symbol, LONG_WINDOW)

                    price_signal = 'NEUTRAL'
                    if short_ma and long_ma:
                        if short_ma > long_ma:
                            price_signal = 'BUY'
                        elif short_ma < long_ma:
                            price_signal = 'SELL'

                    # 2. News-based Signal
                    news_signal = 'NEUTRAL'
                    if sentiment > BULLISH_THRESHOLD:
                        news_signal = 'BUY'
                    elif sentiment < BEARISH_THRESHOLD:
                        news_signal = 'SELL'

                    # 3. Combine Signals
                    final_signal = 'NEUTRAL'
                    if price_signal == 'BUY' and news_signal == 'BUY':
                        final_signal = 'BUY'
                    elif price_signal == 'SELL' and news_signal == 'SELL':
                        final_signal = 'SELL'

                    # --- D. Order Generation ---

                    # Log signal derivation
                    if final_signal != 'NEUTRAL':
                        print(
                            f"[{pid}|{symbol}] SENTIMENT:{sentiment} (News:{news_signal}) | MA_S:{short_ma:.2f} MA_L:{long_ma:.2f} (Price:{price_signal}) -> FINAL:{final_signal}")

                    # Only act if position is NONE or we want to reverse
                    if final_signal == 'BUY' and state.position[symbol] != 'LONG':
                        order = {
                            'order_id': state.order_counter,
                            'symbol': symbol,
                            'side': 'BUY',
                            'quantity': 10,
                            'price': current_price,
                            'timestamp': time.time()
                        }
                        _send_order(om_socket, order)  # Corrected call: removed self.
                        state.position[symbol] = 'LONG'
                        state.order_counter += 1

                    elif final_signal == 'SELL' and state.position[symbol] != 'SHORT':
                        order = {
                            'order_id': state.order_counter,
                            'symbol': symbol,
                            'side': 'SELL',
                            'quantity': 10,
                            'price': current_price,
                            'timestamp': time.time()
                        }
                        _send_order(om_socket, order)  # Corrected call: removed self.
                        state.position[symbol] = 'SHORT'
                        state.order_counter += 1

                time.sleep(0.01)  # Short delay to prevent busy-waiting

        except SocketStreamClosed as e:
            print(f"[{pid}] Connection Error: {e}")
            news_socket.close()
            time.sleep(2)  # Wait before attempting reconnection
        except ConnectionRefusedError:
            print(f"[{pid}] News Gateway Refused. Retrying in 2s...")
            news_socket.close()
            time.sleep(2)
        except Exception as e:
            print(f"[{pid}] Unexpected Error in Strategy loop: {e}", file=sys.stderr)
            news_socket.close()
            time.sleep(2)

    # Cleanup
    om_socket.close()
    close_shared_price_book(shm_book)


if __name__ == '__main__':
    print("Run via main.py for full context.")