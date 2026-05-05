# Sign-in UI Test PRD

## Scope

Validate the UI-only sign-in page at `https://webapp-singkronisasi-dwh.vercel.app/sign-in`.

## Out of Scope

- Do not test real backend authentication.
- Do not submit real credentials.
- Do not require a successful login redirect.

## Test Cases

1. The `/sign-in` page opens successfully.
2. The email or username input is visible.
3. The password input is visible.
4. The login button is visible.
5. Clicking login with an empty form is safe: the page remains on `/sign-in` or validation is shown.

## Expected Behavior

The page should render the sign-in form controls without backend dependency. Empty-form submission should not crash the UI or navigate to an authenticated area.
