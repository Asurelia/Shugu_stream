/**
 * /login — Redirect to canonical unified login page.
 *
 * AUTH-1: the operator login page (/login) is now a redirect to /account/login,
 * which is the single canonical entry point for all users.
 *
 * After login, the /account/login page reads `is_operator` from the response:
 *   - is_operator=true  → redirect to / (activates voiceWiringActive)
 *   - is_operator=false → redirect to /account/profile
 *
 * The legacy /login URL is preserved for bookmarks and external links but
 * permanently redirects to /account/login.
 */
import { redirect } from "next/navigation";

export default function LoginPage() {
  redirect("/account/login");
}
