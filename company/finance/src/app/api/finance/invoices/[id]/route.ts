import { NextRequest, NextResponse } from "next/server";
import { getInvoice, updateInvoice, ValidationError } from "@/lib/invoiceStore";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, PUT, PATCH, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

export async function OPTIONS() {
  return new NextResponse(null, { status: 204, headers: CORS_HEADERS });
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const invoice = getInvoice(id);

  if (!invoice) {
    return NextResponse.json(
      { success: false, error: `Invoice '${id}' not found.` },
      { status: 404, headers: CORS_HEADERS }
    );
  }

  return NextResponse.json(
    { success: true, data: invoice },
    { status: 200, headers: CORS_HEADERS }
  );
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const body = await request.json();
    const updated = updateInvoice(id, body);

    return NextResponse.json(
      { success: true, message: "Invoice updated successfully.", data: updated },
      { status: 200, headers: CORS_HEADERS }
    );
  } catch (err: unknown) {
    if (err instanceof ValidationError) {
      return NextResponse.json(
        {
          success: false,
          error: err.message,
          code: err.code,
          fieldErrors: err.fieldErrors,
        },
        { status: 400, headers: CORS_HEADERS }
      );
    }

    const message = err instanceof Error ? err.message : "Error updating invoice";
    const status = message.includes("not found") ? 404 : 500;

    return NextResponse.json(
      { success: false, error: message },
      { status, headers: CORS_HEADERS }
    );
  }
}
