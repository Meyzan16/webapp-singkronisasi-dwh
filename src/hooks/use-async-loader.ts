import { useCallback, useContext } from "react";
import { GlobalContext } from "@/app/context";

/**
 * Membungkus async action dengan pageLevelLoader secara otomatis.
 * Loader SELALU dimatikan via `finally` — aman dari error maupun lupa memanggil false.
 *
 * @example
 * const run = useAsyncLoader();
 * await run(async () => {
 *   await apiCall();
 *   router.push("/dashboard");
 * });
 */
export function useAsyncLoader() {
  const { setPageLevelLoader } = useContext(GlobalContext)!;

  const run = useCallback(
    async (fn: () => Promise<void>): Promise<void> => {
      setPageLevelLoader(true);
      try {
        await fn();
      } finally {
        setPageLevelLoader(false);
      }
    },
    [setPageLevelLoader]
  );

  return run;
}
