from channels.routing import URLRouter

from boards.routing import websocket_urlpatterns as board_routes
from chat.routing import websocket_urlpatterns as chat_routes

# AuthMiddlewareStack is applied once in asgi.py (do not wrap here too).
websocket_application = URLRouter(chat_routes + board_routes)
