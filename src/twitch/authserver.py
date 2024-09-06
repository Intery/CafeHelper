"""
We want to open an aiohttp server and listen on a configured port.
When we get a request, we validate it to be 'of twitch form',
parse out the error or access token, state, etc, and then pass that information on.

Passing on maybe done through webhook server?
"""
