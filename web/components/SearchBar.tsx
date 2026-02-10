"use client";

import { useState, useCallback } from "react";
import { Search } from "lucide-react";
import { api } from "@/lib/api";
import type { SearchResult } from "@/lib/types";

const SCOPES = [
  { value: "conversations", label: "Conversations" },
  { value: "messages", label: "Messages" },
  { value: "decisions", label: "Decisions" },
  { value: "patterns", label: "Patterns" },
];

export function SearchBar() {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("conversations");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;

    setLoading(true);
    setSearched(true);
    try {
      const data = await api.search(query, scope, 15);
      setResults(data);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [query, scope]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") handleSearch();
    },
    [handleSearch]
  );

  return (
    <div>
      <div className="flex gap-3 items-center">
        <div className="flex-1 relative">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-forge-muted"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Semantic search across Forge OS..."
            className="w-full pl-10 pr-4 py-2.5 bg-forge-card border border-forge-border rounded-lg text-sm text-forge-text placeholder:text-forge-muted focus:outline-none focus:border-forge-accent"
          />
        </div>
        <button
          onClick={handleSearch}
          disabled={loading || !query.trim()}
          className="px-4 py-2.5 bg-forge-accent border border-forge-border rounded-lg text-sm text-forge-text hover:bg-forge-card transition-colors disabled:opacity-50"
        >
          {loading ? "Searching..." : "Search"}
        </button>
      </div>

      <div className="flex gap-2 mt-3">
        {SCOPES.map((s) => (
          <button
            key={s.value}
            onClick={() => setScope(s.value)}
            className={`px-3 py-1.5 rounded text-xs transition-colors ${
              scope === s.value
                ? "bg-forge-card border border-forge-border text-forge-text"
                : "text-forge-muted hover:text-forge-text"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {loading && (
        <p className="text-sm text-forge-muted mt-6">Searching...</p>
      )}

      {searched && !loading && results.length === 0 && (
        <p className="text-sm text-forge-muted mt-6">
          No results found for &ldquo;{query}&rdquo; in {scope}.
        </p>
      )}

      {results.length > 0 && (
        <div className="mt-6 space-y-3">
          {results.map((r, i) => (
            <div
              key={i}
              className="bg-forge-card border border-forge-border rounded-lg p-4"
            >
              <div className="flex items-center gap-3 mb-2">
                <span className="font-mono text-xs text-tier-high">
                  {(r.score ?? 0).toFixed(3)}
                </span>
                {r.project_name && (
                  <span className="text-xs px-2 py-0.5 rounded bg-cross-project/20 text-cross-project">
                    {r.project_name}
                  </span>
                )}
                {r.content_type && (
                  <span className="text-xs text-forge-muted">
                    {r.content_type}
                  </span>
                )}
              </div>
              <p className="text-sm text-forge-text line-clamp-3">
                {r.text}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
