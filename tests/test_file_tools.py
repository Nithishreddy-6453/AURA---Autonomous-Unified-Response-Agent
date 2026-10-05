import asyncio
import json
import unittest
from pathlib import Path

from backend.agent.planner import Planner
from backend.agent.schemas import PlanningResult
from backend.llm.base import LLMProvider
from backend.models.task import Task
from backend.tools.document_extract import DocumentExtractTool
from backend.tools.file_read import ReadCompanyFileTool
from backend.tools.file_search import SearchCompanyFilesTool
from backend.tools import ToolRegistry, get_default_tool_registry


class TestFileTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parent.parent
        cls.data_dir = cls.project_root / "data" / "company"

    def setUp(self):
        self.search_tool = SearchCompanyFilesTool(base_dir=str(self.data_dir))
        self.read_tool = ReadCompanyFileTool(base_dir=str(self.data_dir))
        self.extract_tool = DocumentExtractTool(base_dir=str(self.data_dir))

    def test_search_company_files_acme(self):
        """Test searching for Acme invoices matches both Acme invoices with scores."""
        obs = asyncio.run(self.search_tool.execute(query="Acme invoice", category="invoices"))
        self.assertTrue(obs.success)
        matches = obs.result["matches"]
        self.assertGreaterEqual(len(matches), 2)
        filenames = [m["filename"] for m in matches]
        self.assertIn("acme_invoice_2026_01.txt", filenames)
        self.assertIn("acme_invoice_2026_03.txt", filenames)

    def test_search_company_files_empty_query(self):
        """Test that searching with empty query returns an error."""
        obs = asyncio.run(self.search_tool.execute(query=""))
        self.assertFalse(obs.success)
        self.assertIn("cannot be empty", obs.error)

    def test_read_company_file_success(self):
        """Test reading a valid company file content."""
        obs = asyncio.run(self.read_tool.execute(file_path="invoices/acme_invoice_2026_03.txt"))
        self.assertTrue(obs.success)
        self.assertEqual(obs.result["filename"], "acme_invoice_2026_03.txt")
        self.assertIn("VENDOR: Acme Corp", obs.result["content"])
        self.assertIn("TOTAL_AMOUNT: 18036.00", obs.result["content"])

    def test_read_company_file_missing(self):
        """Test handling of non-existent company file."""
        obs = asyncio.run(self.read_tool.execute(file_path="invoices/missing_file.txt"))
        self.assertFalse(obs.success)
        self.assertIn("File not found", obs.error)

    def test_read_path_traversal_rejection(self):
        """Test that paths attempting directory traversal are strictly rejected."""
        traversal_attempts = [
            "../../requirements.txt",
            "../agent/runtime.py",
            "invoices/../../.env",
            "C:/Windows/win.ini",
        ]
        for bad_path in traversal_attempts:
            obs = asyncio.run(self.read_tool.execute(file_path=bad_path))
            self.assertFalse(obs.success, f"Expected rejection for: {bad_path}")
            self.assertIn("Access denied", obs.error)

    def test_search_category_traversal_rejection(self):
        """Test that directory traversal in search category is rejected."""
        obs = asyncio.run(self.search_tool.execute(query="secret", category="../../"))
        self.assertFalse(obs.success)
        self.assertIn("path traversal", obs.error)

    def test_document_extract_from_text(self):
        """Test structured key-value and amount extraction from raw text."""
        sample_doc = (
            "INVOICE_NUMBER: INV-TEST-01\n"
            "VENDOR: Test Vendor\n"
            "DATE: 2026-05-10\n"
            "TOTAL_AMOUNT: 4500.50\n"
        )
        obs = asyncio.run(self.extract_tool.execute(content=sample_doc))
        self.assertTrue(obs.success)
        fields = obs.result["extracted_fields"]
        self.assertEqual(fields["invoice_number"], "INV-TEST-01")
        self.assertEqual(fields["vendor"], "Test Vendor")
        self.assertEqual(fields["date"], "2026-05-10")
        self.assertEqual(fields["total_amount"], 4500.50)

    def test_document_extract_from_file_path(self):
        """Test structured extraction directly from an existing company invoice file."""
        obs = asyncio.run(self.extract_tool.execute(file_path="invoices/globex_invoice_2026_02.txt"))
        self.assertTrue(obs.success)
        fields = obs.result["extracted_fields"]
        self.assertEqual(fields["invoice_number"], "INV-GLX-4011")
        self.assertEqual(fields["vendor"], "Globex Logistics")
        self.assertEqual(fields["total_amount"], 5886.00)

    def test_document_extract_traversal_rejection(self):
        """Test path traversal rejection in document extraction."""
        obs = asyncio.run(self.extract_tool.execute(file_path="../../requirements.txt"))
        self.assertFalse(obs.success)
        self.assertIn("Access denied", obs.error)

    def test_tool_registration_in_default_registry(self):
        """Test that all three tools are registered in default registry with specifications."""
        registry = get_default_tool_registry()
        self.assertTrue(registry.has("search_company_files"))
        self.assertTrue(registry.has("read_company_file"))
        self.assertTrue(registry.has("document_extract"))

        specs = registry.get_tool_specs()
        spec_names = [s["name"] for s in specs]
        self.assertEqual(spec_names, ["search_company_files", "read_company_file", "document_extract"])


# ---------------------------------------------------------------------------
# Integration Test: Planner uses file tools without hallucinating
# ---------------------------------------------------------------------------

class MockLLMProviderForFilePlanning(LLMProvider):
    """Test double recording received prompt and returning a plan with real file tools."""

    def __init__(self):
        self.last_prompt = ""
        self.last_system_instruction = ""

    async def generate(self, prompt: str, system_instruction: str = None, temperature: float = 0.0, **kwargs):
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction or ""
        # Return a plan strictly utilizing available tools
        return json.dumps({
            "goal": "Find the latest Acme invoice",
            "is_feasible": True,
            "unsupported_reason": None,
            "actions": [
                {
                    "tool_name": "search_company_files",
                    "arguments": {"query": "Acme invoice", "category": "invoices"}
                },
                {
                    "tool_name": "read_company_file",
                    "arguments": {"file_path": "invoices/acme_invoice_2026_03.txt"}
                },
                {
                    "tool_name": "document_extract",
                    "arguments": {"file_path": "invoices/acme_invoice_2026_03.txt"}
                }
            ]
        })

    async def chat(self, messages, temperature: float = 0.0, **kwargs):
        return ""


class TestFileToolsPlanningIntegration(unittest.TestCase):

    def test_planner_chooses_available_file_tools(self):
        """Test that planner receives file tools in prompt and generates a plan with them."""
        registry = get_default_tool_registry()
        mock_llm = MockLLMProviderForFilePlanning()
        planner = Planner(llm_provider=mock_llm, tool_registry=registry)

        task = Task(user_goal="Find the latest Acme invoice.")
        result: PlanningResult = asyncio.run(planner.create_plan(task))

        # Check prompt contains available tool definitions
        self.assertIn("search_company_files", mock_llm.last_prompt)
        self.assertIn("read_company_file", mock_llm.last_prompt)
        self.assertIn("document_extract", mock_llm.last_prompt)

        # Check plan validation succeeded
        self.assertTrue(result.success)
        self.assertEqual(len(result.actions), 3)

        action_tools = [a.tool_name for a in result.actions]
        self.assertEqual(action_tools, ["search_company_files", "read_company_file", "document_extract"])

        # Validate that each planned action tool is registered
        for tool_name in action_tools:
            self.assertTrue(registry.has(tool_name))


if __name__ == "__main__":
    unittest.main()
