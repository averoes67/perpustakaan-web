import sys
import os
import traceback

# Tambahkan direktori root dan api ke sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

try:
    from main import app
except Exception as e:
    startup_error = traceback.format_exc()
    print("CRITICAL VERCEL STARTUP ERROR:\n", startup_error)

    # Fallback ASGI application untuk menampilkan error asli di browser
    async def app(scope, receive, send):
        if scope.get("type") == "http":
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Vercel Startup Error</title>
                <style>
                    body {{ font-family: monospace; background: #0f172a; color: #f8fafc; padding: 24px; }}
                    .box {{ background: #1e293b; border: 2px solid #ef4444; border-radius: 12px; padding: 24px; max-width: 900px; margin: 0 auto; }}
                    h1 {{ color: #ef4444; font-size: 18px; margin-top: 0; }}
                    pre {{ background: #020617; padding: 16px; border-radius: 8px; color: #fca5a5; overflow-x: auto; font-size: 13px; line-height: 1.5; }}
                </style>
            </head>
            <body>
                <div class="box">
                    <h1>Vercel Python Startup Failure</h1>
                    <p>Aplikasi gagal dijalankan saat startup dengan error:</p>
                    <pre>{startup_error}</pre>
                </div>
            </body>
            </html>
            """
            body = html.encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    [b"content-type", b"text/html; charset=utf-8"],
                    [b"content-length", str(len(body)).encode("utf-8")]
                ]
            })
            await send({
                "type": "http.response.body",
                "body": body
            })
        else:
            await send({"type": "http.response.start", "status": 500, "headers": []})
            await send({"type": "http.response.body", "body": b""})
