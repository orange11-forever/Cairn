import { useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchDocuments } from "../api/documents.ts";
import type { ResourceId } from "../schemas/primitives.ts";

export const documentKeys = {
  all: ["documents"] as const,
  list: (userId: ResourceId, scenario: string) => ["documents", userId, scenario] as const,
};

export function useDocumentsQuery(userId: ResourceId, scenario: string) {
  const queryClient = useQueryClient();
  const queryKey = documentKeys.list(userId, scenario);
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => fetchDocuments({ scenario, signal }),
    enabled: false,
  });

  async function cancel(): Promise<void> {
    await queryClient.cancelQueries({ queryKey, exact: true });
    queryClient.removeQueries({ queryKey, exact: true });
  }

  return { ...query, cancel };
}
