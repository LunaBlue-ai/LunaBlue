import { useEffect } from "react";
import { getHealth } from "./api/client";
import { Chat } from "./components/Chat";
import { StatusBar } from "./components/StatusBar";
import { useWebSocket } from "./hooks/useWebSocket";
import { useAppDispatch } from "./state/AppState";

export default function App() {
  const dispatch = useAppDispatch();

  // Live updates: /ws socket with reconnect, plus the polling fallback.
  useWebSocket();

  // One health probe on load so the status bar starts truthful; after that,
  // the socket status and each prompt/poll outcome keep it current.
  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then(() => {
        if (!cancelled) {
          dispatch({ type: "connectivity_changed", connectivity: "connected" });
        }
      })
      .catch(() => {
        if (!cancelled) {
          dispatch({
            type: "connectivity_changed",
            connectivity: "unreachable",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [dispatch]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>LunaBlue</h1>
      </header>
      <Chat />
      <StatusBar />
    </div>
  );
}
