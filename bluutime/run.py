"""Sobe o Bluutime local: http://localhost:8020"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bluutime.server.app:app", host="127.0.0.1",
                port=int(os.environ.get("PORT", 8020)), reload=False)
