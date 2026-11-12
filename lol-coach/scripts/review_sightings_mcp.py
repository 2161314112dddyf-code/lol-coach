"""Serve one host-selected frame, or probe it via a real local MCP stdio client."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from pydantic import TypeAdapter
from typing_extensions import TypedDict

from lol_coach.reasoning_frame import canonical
from lol_coach.review_sightings import check_sighting_answer, enemy_sightings


class PositionSample(TypedDict):
    xz: tuple[float, float]
    sampled_at: float
    age_seconds: float


class Opponent(TypedDict):
    champion: str
    entity_id: str
    visible: bool | None
    last_observed_path_start: PositionSample | None
    fact_id: str | None


class Sightings(TypedDict):
    frame_id: str
    observer_team_id: int
    at_seconds: float
    opponents: list[Opponent]


TOOL = types.Tool(
    name='enemy_sightings',
    description=('Read opponent visibility in the locked team/time frame. visible=null means unknown. '
                 'A path start is the last recorded visible sample, including its age in seconds. '
                 'It cannot establish a hidden position, safe route, or arrival time.'),
    inputSchema={'type': 'object', 'properties': {}, 'additionalProperties': False},
    outputSchema=TypeAdapter(Sightings).json_schema(),
    annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)


async def serve(frame, expected_hash):
    raw = frame.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError('frame_file_changed')
    response = enemy_sightings(json.loads(raw))
    server = Server('lol-review-sightings')

    @server.list_tools()
    async def list_tools():
        return [TOOL]

    @server.call_tool()
    async def call_tool(name, arguments):
        if name != TOOL.name or arguments:
            raise ValueError('only the locked frame is available')
        return response

    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


async def probe(frame):
    raw = frame.read_bytes()
    expected = enemy_sightings(json.loads(raw))
    params = StdioServerParameters(
        command=sys.executable, cwd=str(Path(__file__).resolve().parents[1]),
        args=['-m', 'scripts.review_sightings_mcp', 'serve', str(frame.resolve()),
              '--sha256', hashlib.sha256(raw).hexdigest()])
    async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as client:
        init = await client.initialize()
        entries = (await client.list_tools()).tools
        if (len(entries) != 1 or entries[0].name != TOOL.name
                or entries[0].inputSchema != TOOL.inputSchema or entries[0].outputSchema != TOOL.outputSchema):
            raise ValueError('unexpected_tool_definition')
        result = await client.call_tool(TOOL.name, {})
        if result.isError or result.structuredContent != expected:
            raise ValueError('direct_and_mcp_results_differ')
        for override in ({'at_seconds': expected['at_seconds'] + 1},
                         {'observer_team_id': 300 - expected['observer_team_id']}):
            if not (await client.call_tool(TOOL.name, override)).isError:
                raise ValueError('unexpected_scope_override')
    return dict(protocol=init.protocolVersion, structured_result=expected,
                canonical_frame_bytes=len(canonical(json.loads(raw)).encode()),
                canonical_result_bytes=len(canonical(expected).encode()),
                direct_equals_mcp=True, rejected_scope_overrides=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('probe').add_argument('frame', type=Path)
    check = sub.add_parser('check', help='Check a four-field answer against the host-selected opponent')
    check.add_argument('frame', type=Path)
    check.add_argument('--entity', required=True)
    check.add_argument('--answer', type=Path, required=True)
    service = sub.add_parser('serve')
    service.add_argument('frame', type=Path)
    service.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if args.command == 'serve':
        asyncio.run(serve(args.frame, args.sha256))
    elif args.command == 'check':
        report = check_sighting_answer(json.loads(args.frame.read_bytes()), args.entity,
                                       json.loads(args.answer.read_text(encoding='utf-8-sig')))
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if report['accepted'] else 1
    else:
        print(json.dumps(asyncio.run(probe(args.frame)), ensure_ascii=True, indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
