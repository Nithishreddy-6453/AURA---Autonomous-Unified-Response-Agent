import httpx
from typing import Dict, Any
from backend.verification.verifier import BaseVerifier, VerificationResult

class FinanceInvoiceVerifier(BaseVerifier):
    def __init__(self, base_url: str = "http://localhost:3000"):
        self.base_url = base_url

    async def verify(self, task_metadata: Dict[str, Any], extracted_data: Dict[str, Any]) -> VerificationResult:
        invoice_id = extracted_data.get("invoice_id")
        if not invoice_id:
            return VerificationResult(False, "No invoice_id found in extracted data to verify.")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/api/finance/invoices/{invoice_id}")
                if response.status_code == 404:
                    return VerificationResult(False, f"Invoice {invoice_id} not found in Finance Portal.")
                response.raise_for_status()
                json_resp = response.json()
                actual_data = json_resp.get("data", {}) if isinstance(json_resp, dict) else {}
        except Exception as e:
            return VerificationResult(False, f"Error verifying invoice: {str(e)}")

        mismatches = []
        for key in ["company", "invoice_date", "due_date", "amount"]:
            if key in extracted_data:
                expected_val = str(extracted_data[key])
                actual_val = str(actual_data.get(key, ""))
                
                # Simple normalization (e.g. if amount is 18036 vs 18036.00)
                if key == "amount":
                    try:
                        if float(expected_val) == float(actual_val):
                            continue
                    except ValueError:
                        pass
                        
                if expected_val != actual_val:
                    mismatches.append(f"{key}: expected '{expected_val}', got '{actual_val}'")

        if mismatches:
            return VerificationResult(False, "Data mismatch: " + ", ".join(mismatches), expected=extracted_data, actual=actual_data)
        
        return VerificationResult(True, "Invoice successfully verified.", expected=extracted_data, actual=actual_data)
