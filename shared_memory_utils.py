import multiprocessing as mp
from multiprocessing.shared_memory import SharedMemory, resource_tracker
import numpy as np
import os
import sys
import atexit

SHM_DTYPE = np.dtype([('symbol','U10'),('price','f8')])

class SharedPriceBook:
    """
    Manages access to market data (symbol, price) stored in shared memory
    and synchronized with a lock.
    """
    def __init__(self, symbols: list, shm_name: str, lock: mp.Lock, create: bool = False):
        """
        Initializes the SharedPriceBook.
        :param symbols: List of symbols to track (e.g., ["AAPL", "MSFT"]).
        :param shm_name: The name of the shared memory block.
        :param lock: A multiprocessing.Lock instance for synchronization.
        :param create: If True, creates and initializes the shared memory block.
        """
        self.symbols = sorted(symbols)
        self.shm_name = shm_name
        self.lock = lock
        self.size = len(self.symbols)
        self.shm = None
        self.data_array = None
        self.symbol_to_index = {sym: i for i, sym in enumerate(self.symbols)}

        try:
            if create:
                self.is_creator = True
                buffer_size = self.size * SHM_DTYPE.itemsize
                self.shm = SharedMemory(name=self.shm_name, create=True, size=buffer_size)
                self.data_array = np.ndarray(self.size, dtype=SHM_DTYPE, buffer=self.shm.buf)
                # Initialize symbols and set initial prices to 0.0
                initial_data = [(sym, 0.0) for sym in self.symbols]
                self.data_array[:] = np.array(initial_data, dtype=SHM_DTYPE)
                print(f"[{os.getpid()}] SharedPriceBook created (Size: {buffer_size} bytes)")
                atexit.register(self.cleanup)
            else:
                self.is_creator = False
                # Attach to an existing shared memory block
                self.shm = SharedMemory(name=self.shm_name, create=False)
                self.data_array = np.ndarray(self.size, dtype=SHM_DTYPE, buffer=self.shm.buf)
                print(f"[{os.getpid()}] SharedPriceBook attached to existing memory.")

        except FileNotFoundError:
            print(f"[{os.getpid()}] Error: Shared memory '{self.shm_name}' not found.", file=sys.stderr)
            raise
        except Exception as e:
            print(f"[{os.getpid()}] Error initializing SharedPriceBook: {e}", file=sys.stderr)
            raise

    def update(self, symbol: str, price: float):
        """
        Updates the price for a specific symbol in the shared memory.
        Uses the lock to ensure atomicity.
        """
        if symbol not in self.symbol_to_index:
            return

        index = self.symbol_to_index[symbol]
        with self.lock:
            # Update only the price field for the symbol's index
            self.data_array['price'][index] = price

    def read_all(self) -> dict:
        """
        Reads all symbol prices from shared memory.
        """
        with self.lock:
            # Create a copy of the current state
            current_state = {row['symbol']: row['price'] for row in self.data_array}
        return current_state

    def cleanup(self):
        """
        Cleans up and unlinks the shared memory segment.
        The unlink attempt is protected by self.is_creator.
        """
        if self.shm:
            try:
                self.shm.close()
                if self.is_creator:
                    # Attempt to unlink only if this process created it
                    self.shm.unlink()
                    print(f"\n[{os.getpid()}] Shared memory '{self.shm_name}' unlinked and closed.")
            except FileNotFoundError:
                # Catch case where it was already unlinked by a forceful exit
                pass
            except Exception as e:
                # Catch other potential errors during cleanup
                print(f"[{os.getpid()}] Error during final cleanup/unlink: {e}", file=sys.stderr)

# Helper function to detach and close (used by client processes)
def close_shared_price_book(shm_instance: SharedMemory):
    """Closes the shared memory attachment for client processes."""
    if shm_instance and shm_instance.shm:
        shm_instance.shm.close()
        print(f"[{os.getpid()}] SharedPriceBook attachment closed.")

# Custom exception for clean socket handling
class SocketStreamClosed(Exception):
    """Raised when a socket connection is closed or fails unexpectedly."""
    pass