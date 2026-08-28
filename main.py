"""Main entry point for LogiRoute Agent: CLI interface, interactive mode, and demo runner."""

import argparse
import sys
import uvicorn

from logiroute.config import config
from logiroute.orchestration import LogisticsOrchestrator

BANNER = r"""
========================================================================
  _                 _ _____             _             _                    _   
 | |               (_)  __ \           | |           / \                  | |  
 | |     ___   __ _ _| |__) |___  _   _| |_ ___     / _ \   __ _  ___ _ __ | |_ 
 | |    / _ \ / _` | |  _  // _ \| | | | __/ _ \   / ___ \ / _` |/ _ \ '_ \| __|
 | |___| (_) | (_| | | | \ \ (_) | |_| | ||  __/  / ___  \ (_| |  __/ | | | |_ 
 |______\___/ \__, |_|_|  \_\___/ \__,_|\__\___| /_/   \_\\__, |\___|_| |_|\__|
               __/ |                                        __/ |               
              |___/                                        |___/                
 Autonomous Logistics & Disruption Resolution Agent (Google Cloud ADK)
========================================================================
"""


def run_demo(orchestrator: LogisticsOrchestrator) -> None:
    """Executes a showcase of logistics disruption resolution scenarios."""
    print("\n" + "=" * 70)
    print(">>> RUNNING LOGIROUTE DEMONSTRATION SUITE")
    print("=" * 70)
    
    scenarios = [
        (
            "SCENARIO 1: Critical Cold-Chain Vaccine Breach",
            "Urgent: Check shipment SHP-MED001. We received a cold chain telemetry warning. What is the status and what is the mitigation plan?",
        ),
        (
            "SCENARIO 2: Severe Blizzard Highway Closure",
            "Shipment SHP-ELC002 is held up in Washington. Diagnose the delay cause and find the best detour route.",
        ),
        (
            "SCENARIO 3: Regional Inventory Stockout & Cross-Dock Lookup",
            "We have a stock shortage in the Southeast. Locate inventory for SKU MED-VAX-882 across our regional distribution centers.",
        ),
    ]

    for title, query in scenarios:
        print(f"\n{'=' * 70}")
        print(f">>> {title}")
        print(f">>> Dispatcher Query: \"{query}\"")
        print(f"{'=' * 70}\n")
        
        result = orchestrator.process_query(query, session_id="demo-session")
        print(result["response"])
        print("\n--- Telemetry & Observability ---")
        print(f"Mode: {result['mode']} | Correlation ID: {result['correlation_id']}")
        print(f"ADK Tools Invoked: {result.get('tools_invoked', [])}")
        print("-" * 70)


def interactive_cli(orchestrator: LogisticsOrchestrator) -> None:
    """Interactive command-line chat session with LogiRoute."""
    print(BANNER)
    print("Type your logistics query or command. Commands: 'demo', 'exit', 'quit', 'clear'.\n")
    
    session_id = "cli-interactive-session"
    
    while True:
        try:
            user_input = input("\033[1;34mDispatcher > \033[0m").strip()
            if not user_input:
                continue
            
            if user_input.lower() in ("exit", "quit", "q"):
                print("\nExiting LogiRoute. Safe journeys!\n")
                break
            
            if user_input.lower() == "demo":
                run_demo(orchestrator)
                continue
            
            if user_input.lower() == "clear":
                print("\033[H\033[J")
                print(BANNER)
                continue

            result = orchestrator.process_query(user_input, session_id=session_id)
            print("\n" + result["response"] + "\n")
            print(f"\033[2m[ADK Tools: {', '.join(result.get('tools_invoked', [])) or 'None'} | Trace: {result['correlation_id'][:16]}]\033[0m\n")

        except (KeyboardInterrupt, EOFError):
            print("\nSession interrupted. Exiting LogiRoute.")
            break


def main():
    """CLI argument parser and dispatcher."""
    parser = argparse.ArgumentParser(description="LogiRoute Agent - Google Cloud ADK Logistics Dispatcher")
    parser.add_argument("--demo", action="store_true", help="Run automated demonstration scenarios")
    parser.add_argument("--query", type=str, help="Run a single dispatch query and exit")
    parser.add_argument("--server", action="store_true", help="Launch FastAPI REST API server")
    parser.add_argument("--port", type=int, default=config.port, help=f"Server port (default: {config.port})")
    parser.add_argument("--host", type=str, default=config.host, help=f"Server host (default: {config.host})")
    
    args = parser.parse_args()
    
    if args.server:
        print(f"Starting LogiRoute REST API on http://{args.host}:{args.port}")
        uvicorn.run("logiroute.api.server:app", host=args.host, port=args.port, reload=False)
        return

    orchestrator = LogisticsOrchestrator()
    
    if args.demo:
        run_demo(orchestrator)
    elif args.query:
        res = orchestrator.process_query(args.query)
        print(res["response"])
    else:
        interactive_cli(orchestrator)


if __name__ == "__main__":
    main()
