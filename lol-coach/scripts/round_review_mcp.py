"""One stdio session serving the round locked by the host."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from lol_coach.round_chain import _check_bundle
from lol_coach.round_tools import ROUND_TOOLS, round_call


async def serve(path, sha256):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError('round_bundle_changed')
    bundle = json.loads(raw)
    _check_bundle(bundle)
    server = Server('lol-round-review')
    definitions = [types.Tool(name=f['name'], description=f['description'], inputSchema=f['parameters'],
        annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False))
        for f in (tool['function'] for tool in ROUND_TOOLS)]

    @server.list_tools()
    async def list_tools():
        return definitions

    @server.call_tool()
    async def call(name, arguments):
        return round_call(bundle, name, arguments)

    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


@asynccontextmanager
async def round_client(path, expected_hash):
    params = StdioServerParameters(command=sys.executable, cwd=str(Path(__file__).resolve().parents[1]),
        args=['-m','scripts.round_review_mcp',str(path.resolve()),expected_hash])
    async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as client:
        init = await client.initialize()
        offered = (await client.list_tools()).tools
        if {t.name:t.inputSchema for t in offered} != {t['function']['name']:t['function']['parameters'] for t in ROUND_TOOLS}:
            raise ValueError('round_tool_discovery_mismatch')
        yield client, init.protocolVersion


async def query(client, name, arguments):
    response = await client.call_tool(name, arguments)
    if response.isError or not isinstance(response.structuredContent, dict):
        raise ValueError('MCP rejected '+name)
    return response.structuredContent


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('sha256')
    args = parser.parse_args()
    asyncio.run(serve(args.bundle, args.sha256))
