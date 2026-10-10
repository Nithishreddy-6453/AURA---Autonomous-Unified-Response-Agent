import { NextResponse } from "next/server";
import { resetStore } from "@/lib/onboardingStore";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

export async function OPTIONS() {
  return new NextResponse(null, { status: 204, headers: CORS_HEADERS });
}

export async function POST() {
  resetStore();
  return NextResponse.json(
    { success: true, message: "HR Onboarding store reset to initial seed data." },
    { status: 200, headers: CORS_HEADERS }
  );
}
