import multiprocessing as mp
import time
import os
import signal
import sys
from typing import List, Optional

# Import components
from gateway import run_gateway
from OrderBook import run_orderbook
from Strategy import run_strategy
from OrderManager import run_ordermanager
from shared_memory_utils import SharedPriceBook, close_shared_price_book

SYMBOLS = ["AAPL", "MSFT", "GOOGL"]
SHM_NAME = "trading_shm_book"


def cleanup_processes(processes: List[mp.Process], shm_book: Optional[SharedPriceBook]):
    """Terminates processes and cleans up shared memory."""
    print("\n[MAIN] Shutting down system components...")

    # 1. Terminate all child processes forcefully
    for p in processes:
        if p.is_alive():
            print(f"[MAIN] Terminating process {p.name} (PID: {p.pid})...")
            # We use terminate/join here to stop execution immediately
            p.terminate()
            p.join(timeout=1)

    # 2. Clean up shared memory (only done by the creator process)
    # The SharedPriceBook class itself contains the logic to unlink if it was the creator.
    # We explicitly call the cleanup method here to ensure unlink happens
    # immediately before the main process exits.
    if shm_book and hasattr(shm_book, 'cleanup'):
        try:
            shm_book.cleanup()
        except Exception as e:
            print(f"[MAIN|ERROR] Error during SharedPriceBook cleanup: {e}", file=sys.stderr)

    print("[MAIN] System shutdown complete.")


def run_system():
    """Initializes shared memory, launches all processes, and waits for termination."""

    # 1. Initialize Shared Resources
    shm_lock = mp.Lock()
    shm_book: Optional[SharedPriceBook] = None

    try:
        # Create and initialize the SharedPriceBook
        shm_book = SharedPriceBook(symbols=SYMBOLS, shm_name=SHM_NAME, lock=shm_lock, create=True)
    except Exception as e:
        print(f"[MAIN] Fatal error during SharedPriceBook creation: {e}", file=sys.stderr)
        return

    # 2. Define Processes
    processes = [
        mp.Process(target=run_gateway, name="Gateway"),
        mp.Process(target=run_orderbook, args=(SHM_NAME, shm_lock, SYMBOLS), name="OrderBook"),
        mp.Process(target=run_strategy, args=(SHM_NAME, shm_lock, SYMBOLS), name="Strategy"),
        mp.Process(target=run_ordermanager, name="OrderManager"),
    ]

    # 3. Start Processes (in reverse order for dependencies to start listening first)
    print("\n[MAIN] Starting system processes...")
    for p in reversed(processes):
        p.start()
        time.sleep(0.5)  # Give servers a moment to bind ports

    # 4. Handle Shutdown (SIGINT/Ctrl+C)
    def signal_handler(sig, frame):
        print("\n[MAIN] Ctrl+C received. Initiating shutdown...")
        # Pass the created shm_book object to cleanup
        cleanup_processes(processes, shm_book)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # 5. Keep main process alive
    try:
        while any(p.is_alive() for p in processes):
            time.sleep(1)
    except SystemExit:
        pass
    except Exception as e:
        print(f"\n[MAIN] Unexpected exception: {e}")
        cleanup_processes(processes, shm_book)

    # Final cleanup if loop exited for other reasons
    cleanup_processes(processes, shm_book)


if __name__ == "__main__":
    run_system()
