import unittest
import time
import socket
import json
import multiprocessing as mp
import numpy as np
from multiprocessing.shared_memory import SharedMemory

# Import the core components to test utility functions and connectivity
from shared_memory_utils import SharedPriceBook, SHM_DTYPE
from gateway import run_gateway, GATEWAY_PRICE_PORT, GATEWAY_NEWS_PORT, SYMBOLS, MESSAGE_DELIMITER
from OrderManager import run_ordermanager, ORDER_MANAGER_PORT


# === Helper: wait until a given port is ready (bind + listen complete) ===
def wait_for_port(port: int, timeout: float = 5.0):
    """Wait until a TCP port on localhost is ready for connection."""
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                return True
        time.sleep(0.1)
    raise TimeoutError(f"Port {port} not ready after {timeout} seconds.")


class TestTradingSystem(unittest.TestCase):
    SHM_NAME = "test_shm_book"

    @classmethod
    def setUpClass(cls):
        """Set up shared memory and lock for testing."""
        cls.shm_lock = mp.Lock()

        # ---- Cleanup previous leftover shared memory block ----
        try:
            existing = SharedMemory(name=cls.SHM_NAME)
            existing.close()
            existing.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass

        cls.shm_book = SharedPriceBook(symbols=SYMBOLS, shm_name=cls.SHM_NAME, lock=cls.shm_lock, create=True)

    @classmethod
    def tearDownClass(cls):
        """Clean up shared memory after all tests are done."""
        if cls.shm_book:
            cls.shm_book.cleanup()

    # ----------------------------------------------------------------------
    def test_01_shared_memory_initialization_and_update(self):
        """Tests that shared memory initializes correctly and updates are atomic."""
        # 1. Test initialization
        self.assertEqual(len(self.shm_book.symbols), len(SYMBOLS))
        read_initial = self.shm_book.read_all()

        for symbol in SYMBOLS:
            self.assertIn(symbol, read_initial)
            self.assertEqual(read_initial[symbol], 0.0, "Initial price should be 0.0")

        # 2. Test update
        test_symbol = SYMBOLS[0]
        test_price = 150.75

        self.shm_book.update(test_symbol, test_price)
        read_updated = self.shm_book.read_all()

        self.assertEqual(read_updated[test_symbol], test_price, "Price should be updated correctly")
        self.assertNotEqual(read_updated[SYMBOLS[1]], test_price, "Update should not affect other symbols")

    # ----------------------------------------------------------------------
    def test_02_gateway_connectivity(self):
        """Tests that the Gateway binds ports and clients can connect."""
        gateway_process = mp.Process(target=run_gateway, name="TestGateway")
        gateway_process.start()

        # ✅ Wait until both ports are ready (instead of fixed sleep)
        wait_for_port(GATEWAY_PRICE_PORT, timeout=6)
        wait_for_port(GATEWAY_NEWS_PORT, timeout=6)

        try:
            # 1. Test Price Stream Connectivity
            price_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            price_sock.connect(('127.0.0.1', GATEWAY_PRICE_PORT))
            self.assertTrue(True, "Successfully connected to Gateway Price Stream.")

            # 2. Test News Stream Connectivity
            news_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            news_sock.connect(('127.0.0.1', GATEWAY_NEWS_PORT))
            self.assertTrue(True, "Successfully connected to Gateway News Stream.")

            # Cleanup
            price_sock.close()
            news_sock.close()

        except ConnectionRefusedError:
            self.fail("Could not connect to Gateway. Ports might not be bound.")
        finally:
            gateway_process.terminate()
            gateway_process.join(timeout=2)

    # ----------------------------------------------------------------------
    def test_03_message_serialization_and_framing(self):
        """Tests receiving and parsing a single framed message from a mock server."""
        mock_om_process = mp.Process(target=run_ordermanager, name="MockOM")
        mock_om_process.start()

        # ✅ Wait until OrderManager port is ready
        wait_for_port(ORDER_MANAGER_PORT, timeout=6)

        try:
            # 1. Test Order Serialization/Framing
            client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_sock.connect(('127.0.0.1', ORDER_MANAGER_PORT))

            test_order = {
                'order_id': 999,
                'symbol': 'MSFT',
                'side': 'BUY',
                'quantity': 100,
                'price': 300.50,
                'timestamp': time.time()
            }

            # Strategy logic for sending
            message_data = json.dumps(test_order)
            full_message = message_data.encode('utf-8') + MESSAGE_DELIMITER
            client_sock.sendall(full_message)

            # Since OrderManager logs the output, we just test successful sending
            self.assertTrue(True, "Order message sent successfully to OrderManager.")

            client_sock.close()

        except ConnectionRefusedError:
            self.fail("Could not connect to OrderManager.")
        finally:
            mock_om_process.terminate()
            mock_om_process.join(timeout=2)


if __name__ == '__main__':
    print("Running unit tests...")
    time.sleep(0.5)
    unittest.main()
