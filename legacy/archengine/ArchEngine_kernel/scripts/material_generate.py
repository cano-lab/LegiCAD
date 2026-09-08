import argparse
import json
import sys
import urllib.request


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a tileable PBR material via render_server.")
    parser.add_argument("--prompt", required=True, help="Text prompt for material generation")
    parser.add_argument("--name", required=True, help="Material name (folder name)")
    parser.add_argument("--server", default="http://localhost:5000", help="render_server base URL")
    parser.add_argument("--size", type=int, default=1024, help="Output size (square, default 1024)")
    parser.add_argument("--steps", type=int, default=30, help="Diffusion steps")
    parser.add_argument("--guidance", type=float, default=7.5, help="Guidance scale")
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument("--tileable", action="store_true", default=True, help="Generate tileable texture")
    parser.add_argument("--no-tileable", dest="tileable", action="store_false", help="Disable tiling")
    parser.add_argument("--seam-width", type=int, default=None, help="Seam inpaint width (pixels)")
    parser.add_argument("--negative", default="blurry, low quality, distorted, watermark", help="Negative prompt")
    parser.add_argument("--output-root", default="materials", help="Output root directory")
    parser.add_argument("--roughness", type=float, default=None, help="Constant roughness [0-1]")
    parser.add_argument("--metallic", type=float, default=None, help="Constant metallic [0-1]")
    parser.add_argument("--emissive", type=float, default=None, help="Constant emissive [0-1]")
    parser.add_argument("--opacity", type=float, default=None, help="Constant opacity [0-1]")

    args = parser.parse_args()

    payload = {
        "prompt": args.prompt,
        "name": args.name,
        "size": args.size,
        "steps": args.steps,
        "guidance": args.guidance,
        "seed": args.seed,
        "tileable": args.tileable,
        "negative_prompt": args.negative,
        "output_root": args.output_root,
    }

    if args.seam_width is not None:
        payload["seam_width"] = args.seam_width
    if args.roughness is not None:
        payload["roughness"] = args.roughness
    if args.metallic is not None:
        payload["metallic"] = args.metallic
    if args.emissive is not None:
        payload["emissive"] = args.emissive
    if args.opacity is not None:
        payload["opacity"] = args.opacity

    url = args.server.rstrip("/") + "/api/materials/generate"

    try:
        result = _post_json(url, payload)
    except Exception as exc:
        print(f"Error calling {url}: {exc}", file=sys.stderr)
        return 1

    if result.get("status") != "ok":
        print(json.dumps(result, indent=2))
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
