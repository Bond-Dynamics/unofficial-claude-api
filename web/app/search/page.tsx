import { SearchBar } from "@/components/SearchBar";

export default function SearchPage() {
  return (
    <div>
      <h1 className="text-xl font-bold text-forge-text mb-2">
        Semantic Search
      </h1>
      <p className="text-sm text-forge-muted mb-6">
        Vector search across conversations, messages, decisions, and patterns
      </p>

      <SearchBar />
    </div>
  );
}
