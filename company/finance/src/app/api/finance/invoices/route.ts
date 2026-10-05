import { NextRequest, NextResponse } from "next/server";
import { listInvoices, createInvoice, ValidationError, DuplicateError } from "@/lib/invoiceStore";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

export async function OPTIONS() {
  return new NextResponse(null, { status: 204, headers: CORS_HEADERS });
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const q = searchParams.get("q") || undefined;
  const invoices = listInvoices(q);

  return NextResponse.json(
    { success: true, count: invoices.length, data: invoices },
    { status: 200, headers: CORS_HEADERS }
  );
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const created = createInvoice(body);

    return NextResponse.json(
      { success: true, message: "Invoice created successfully.", data: created },
      { status: 201, headers: CORS_HEADERS }
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
    if (err instanceof DuplicateError) {
      return NextResponse.json(
        {
          success: false,
          error: err.message,
          code: err.code,
        },
        { status: 409, headers: CORS_HEADERS }
      );
    }

    const message = err instanceof Error ? err.message : "Internal Server Error";
    return NextResponse.json(
      { success: false, error: message },
      { status: 500, headers: CORS_HEADERS }
    );
  }
}
