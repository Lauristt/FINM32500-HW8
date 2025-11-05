# Assignment 8: Inter-Process Communication for Trading Systems

This project implements a simplified multi-process trading stack featuring real-time communication between independent system components via TCP sockets and shared memory.  
It simulates the architecture of modern low-latency trading infrastructures—comprising a Gateway, OrderBook, Strategy, and OrderManager—that exchange market data and orders in real time.

**Author:** Yuting Li  
**Course:** FINM 32500 – University of Chicago  

![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green)
![Build Passing](https://img.shields.io/badge/build-passing-brightgreen)

---

## Overview

The trading system demonstrates how multiple processes communicate through:
- Shared Memory (multiprocessing.shared_memory) for efficient price-book updates.
- Socket-based Inter-Process Communication for message-driven interactions among components.
- Serialization and Message Framing for transmitting structured data between processes.

Each component runs as an independent process:
1. Gateway – Emits price and news ticks to clients.  
2. OrderBook – Maintains shared memory of latest prices.  
3. Strategy – Reacts to news ticks and generates trade orders.  
4. OrderManager – Receives and logs orders from strategies.

---

## Architecture

+------------+        +------------+        +--------------+        +---------------+
|  Gateway   |  -->   | OrderBook  |  -->   |  Strategy    |  -->   | OrderManager  |
| (TCP feed) |        | (SharedMem)|        | (Decision)   |        | (Execution)   |
+------------+        +------------+        +--------------+        +---------------+
         ^--------------------------------------------------------------------------+
                         Message passing via sockets + shared memory

---

## Implementation Highlights

### 1. Shared Memory Design
The system uses a SharedPriceBook implemented with a NumPy structured array:

dtype=[('symbol','U10'),('price','f8')]

| Metric | Value | Description |
| :------ | :---- | :----------- |
| Number of Symbols | 3 (AAPL, MSFT, GOOGL) | Defined in main.py |
| Memory per element | 24 bytes | U10 (20 bytes) + f8 (8 bytes) |
| Total Memory Footprint | 72 bytes | Highly efficient NumPy structure |

---

### 2. Process Connectivity
Each process binds to a specific TCP port:
| Component | Port Range | Role |
| :--------- | :--------- | :---- |
| Gateway | 8000 – 8001 | Sends tick data |
| OrderManager | 8002 | Listens for orders |
| Strategy | Dynamic (local loopback connection) | Sends order messages |

All connections are bi-directional and use JSON-encoded messages with headers for framing.

---

### 3. Testing and Validation
Unit tests verify:
- Shared memory initialization and update.
- Gateway connectivity and socket messaging.
- Message serialization and framing logic.

Pytest Results (Successful Run)

============================= test session starts ==============================
collecting ... collected 3 items

UnitTest.py::TestTradingSystem::test_01_shared_memory_initialization_and_update
UnitTest.py::TestTradingSystem::test_02_gateway_connectivity
UnitTest.py::TestTradingSystem::test_03_message_serialization_and_framing

========================== 3 passed in 0.50s ==========================
[95049] SharedPriceBook created (Size: 144 bytes)
[95052] Starting OrderManager...
[OM] Listening for Strategy clients on 127.0.0.1:8002...
[OM] Accepted connection from Strategy (127.0.0.1, 49453)
[OM] Strategy client disconnected – waiting for new connection...
[OM] Accepted connection from Strategy (127.0.0.1, 49454)
[95049] Shared memory 'test_shm_book' unlinked and closed.
Process finished with exit code 0

---

## Performance Report Summary

### Environment
- 8-core CPU, 16GB RAM
- Python 3.10
- NumPy for structured shared memory
- Socket and multiprocessing for IPC

### Latency and Throughput

| Metric | Value | Notes |
| :------ | :---- | :---- |
| Average Execution Latency | 3.2 ms | Tick-to-trade latency |
| Price Stream | 99.5 ticks/sec | Target 100 ticks/sec |
| News Stream | 2.0 ticks/sec | Stable delivery |

### Reliability
- Reconnection logic for Gateway and Strategy upon socket failure
- JSONDecodeError handling for corrupted messages
- Skip signals on uninitialized shared memory (price=0.0)

---

## File Structure

main.py  
gateway.py  
OrderBook.py  
Strategy.py  
OrderManager.py  
shared_memory_utils.py  
performance_report.md  
unittest_results.png  
video.mp4  

---

## License

MIT License © 2025 Yuting Li  
