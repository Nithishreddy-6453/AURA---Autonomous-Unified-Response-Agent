import { NextRequest, NextResponse } from "next/server";
import { getOnboarding, updateOnboarding, ValidationError } from "@/lib/onboardingStore";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, PATCH, OPTIONS",
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
  const record = getOnboarding(id);

  if (!record) {
    return NextResponse.json(
      { success: false, error: `Onboarding record '${id}' not found.` },
      { status: 404, headers: CORS_HEADERS }
    );
  }

  return NextResponse.json(
    { success: true, data: record },
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
    const updated = updateOnboarding(id, body);

    return NextResponse.json(
      { success: true, message: "Onboarding record updated successfully.", data: updated },
      { status: 200, headers: CORS_HEADERS }
    );
  } catch (err: unknown) {
    if (err instanceof ValidationError) {
      return NextResponse.json(
        { success: false, error: err.message, code: err.code, fieldErrors: err.fieldErrors },
        { status: 400, headers: CORS_HEADERS }
      );
    }
    const message = err instanceof Error ? err.message : "Internal Server Error";
    return NextResponse.json(
      { success: false, error: message },
      { status: 400, headers: CORS_HEADERS }
    );
  }
}
