import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import Demo from "./pages/Demo.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import "./index.css";

const isDemo = window.location.pathname === "/demo";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      {isDemo ? <Demo /> : <App />}
    </ErrorBoundary>
  </React.StrictMode>
);
