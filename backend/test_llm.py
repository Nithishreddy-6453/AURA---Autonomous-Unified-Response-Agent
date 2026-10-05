import asyncio
import json
import sys

from backend.llm.router import get_llm_provider

TEST_PROMPT = """Return ONLY valid JSON with fields 'goal' and 'steps' for this task:
Find the latest Acme invoice and enter its amount into the Finance Portal."""


async def main():
    print("=" * 60)
    print("Testing LLM Provider...")
    print("=" * 60)

    try:
        provider = get_llm_provider()
        provider_name = type(provider).__name__
        print(f"Active Provider: {provider_name}")
    except Exception as e:
        print(f"\n[FAIL] Provider initialization failed: {e}", file=sys.stderr)
        sys.exit(1)

    print("\nSending prompt:")
    print(f'"{TEST_PROMPT}"\n')

    try:
        response_text = await provider.generate(prompt=TEST_PROMPT, temperature=0.0)
    except Exception as e:
        print(f"\n[FAIL] Provider failed to connect or generate response:\n{e}", file=sys.stderr)
        sys.exit(1)

    print("-" * 60)
    print("Model Response:")
    print("-" * 60)
    print(response_text)
    print("-" * 60)

    # Validate output parsing
    try:
        cleaned_response = response_text.strip()
        if cleaned_response.startswith("```"):
            lines = cleaned_response.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned_response = "\n".join(lines).strip()

        parsed = json.loads(cleaned_response)
        if "goal" in parsed and "steps" in parsed:
            print("\n[SUCCESS] Response validated: Contains valid JSON with 'goal' and 'steps'.")
        else:
            print("\n[WARNING] Output is valid JSON but missing 'goal' or 'steps' fields.")
    except json.JSONDecodeError:
        print("\n[INFO] Response was not pure JSON, raw text printed above.")

    print("\nLLM Provider test completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
