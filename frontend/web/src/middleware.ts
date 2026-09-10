import { NextResponse, type NextRequest } from "next/server";

/**
 * A redirect-only route guard. It checks for the presence of the session cookie
 * and bounces the browser to `/login` (or away from `/login` when already
 * signed in). **This is a UX affordance, not authorization** — every API call is
 * still authenticated and permission-checked server-side by the BFF. A forged or
 * expired cookie simply yields 401s from the API, which the app handles.
 */

const SESSION_COOKIE = "sm_session";
const PUBLIC_PATHS = ["/login"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const hasSession = req.cookies.has(SESSION_COOKIE);
  const isPublic = PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  if (!hasSession && !isPublic) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  if (hasSession && isPublic) {
    const url = req.nextUrl.clone();
    url.pathname = "/";
    url.search = "";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // everything except Next internals, the API proxy, and static assets
  matcher: ["/((?!_next/static|_next/image|api/|favicon.ico).*)"],
};
