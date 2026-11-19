<script lang="ts">
  import { formatCaseNavigatorLabel, type CaseDisplayMetadata } from '$lib/caseDisplay';

  type CaseNavigatorItem = {
    case_id: number;
    metadata: CaseDisplayMetadata;
  };

  export let items: CaseNavigatorItem[] = [];
  export let selectedCaseId: number | null = null;
  export let visibleCaseIds: number[] = [];
  export let maxItems: number | null = null;
  export let itemLabel = 'cases';
  export let ariaLabel = 'Available cases';
  export let searchPlaceholder = 'Child or animal name';
  export let emptyMessage = '';

  let searchQuery = '';
  let filteredItems: CaseNavigatorItem[] = [];

  $: filteredItems = items.filter((item) => matchesSearch(item, searchQuery));
  $: visibleCaseIds = filteredItems.map((item) => item.case_id);
  $: if (!visibleCaseIds.includes(selectedCaseId ?? -1)) {
    selectedCaseId = visibleCaseIds[0] ?? null;
  }

  function matchesSearch(item: CaseNavigatorItem, query: string): boolean {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    if (!normalizedQuery) {
      return true;
    }

    return formatCaseNavigatorLabel(item.metadata).toLocaleLowerCase().includes(normalizedQuery);
  }

  function clearSearch(): void {
    searchQuery = '';
  }
</script>

<aside class="card case-navigator" aria-label={ariaLabel}>
  <label for="case-search">Search {itemLabel}</label>
  <input
    id="case-search"
    type="search"
    bind:value={searchQuery}
    placeholder={searchPlaceholder}
  />

  <p class="case-count">
    {filteredItems.length} of {items.length} {itemLabel}
    {#if maxItems !== null}
      <span>(up to {maxItems} retained)</span>
    {/if}
  </p>

  {#if items.length === 0 && emptyMessage}
    <p>{emptyMessage}</p>
  {:else if filteredItems.length === 0}
    <div class="empty-search">
      <p>No matching {itemLabel}.</p>
      <button class="secondary" on:click={clearSearch}>Clear search</button>
    </div>
  {:else}
    <nav class="case-list" aria-label={ariaLabel}>
      {#each filteredItems as item (item.case_id)}
        <button
          class:active={item.case_id === selectedCaseId}
          aria-pressed={item.case_id === selectedCaseId}
          on:click={() => (selectedCaseId = item.case_id)}
        >
          {formatCaseNavigatorLabel(item.metadata)}
        </button>
      {/each}
    </nav>
  {/if}
</aside>

<style>
  .case-navigator {
    position: sticky;
    top: 1rem;
  }

  .case-navigator > label {
    font-weight: 700;
  }

  .case-count {
    display: grid;
    gap: 0.1rem;
    margin: 0.75rem 0;
    color: #4f5a60;
  }

  .case-count span {
    font-size: 0.875rem;
  }

  .case-list {
    display: grid;
    gap: 0.4rem;
    padding: 0;
    border: 0;
    background: transparent;
    backdrop-filter: none;
  }

  .case-list button {
    width: 100%;
    overflow-wrap: anywhere;
    border-color: var(--border);
    background: white;
    color: var(--text);
    text-align: left;
  }

  .case-list button:hover,
  .case-list button.active {
    border-color: var(--accent);
    background: rgba(14, 124, 123, 0.1);
  }

  .case-list button.active {
    box-shadow: inset 4px 0 0 var(--accent);
    font-weight: 700;
  }

  .empty-search p {
    margin-bottom: 0.6rem;
  }

  @media (max-width: 760px) {
    .case-navigator {
      position: static;
    }

    .case-list {
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    }
  }
</style>
