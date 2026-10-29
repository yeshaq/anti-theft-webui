<script lang="ts">
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	import { getContext, onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';

	import { WEBUI_NAME, config, models, showSidebar, user } from '$lib/stores';
	import {
		deleteAutomationById,
		getAutomationRuns,
		getAutomations,
		runAutomationById,
		toggleAutomationById,
		type Automation,
		type AutomationRun
	} from '$lib/apis/automations';
	import { describeSchedule } from '$lib/components/automations/schedule';

	import AutomationModal from '$lib/components/automations/AutomationModal.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import Clock from '$lib/components/icons/Clock.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';

	dayjs.extend(relativeTime);

	const i18n = getContext('i18n');

	let automations: Automation[] | null = null;
	let showModal = false;
	let editing: Automation | null = null;
	let showDeleteConfirm = false;
	let deleting: Automation | null = null;

	let expandedId: string | null = null;
	let runs: AutomationRun[] = [];

	let pollTimer: ReturnType<typeof setInterval> | undefined;

	$: modelName = (id: string) => $models.find((m) => m.id === id)?.name ?? id;
	$: anyRunning = (automations ?? []).some((a) => a.last_run?.status === 'running');
	$: syncPolling(anyRunning);

	const load = async () => {
		try {
			automations = await getAutomations(localStorage.token);
			if (expandedId) {
				runs = await getAutomationRuns(localStorage.token, expandedId);
			}
		} catch (error) {
			toast.error(`${error}`);
			automations = automations ?? [];
		}
	};

	// While a run is in flight, refresh so its status flips without a reload.
	const syncPolling = (running: boolean) => {
		if (running && !pollTimer) {
			pollTimer = setInterval(load, 3000);
		} else if (!running && pollTimer) {
			clearInterval(pollTimer);
			pollTimer = undefined;
		}
	};

	const replace = (updated: Automation) => {
		const exists = (automations ?? []).some((a) => a.id === updated.id);
		automations = exists
			? automations!.map((a) => (a.id === updated.id ? updated : a))
			: [updated, ...(automations ?? [])];
	};

	const toggleHandler = async (automation: Automation) => {
		try {
			replace(await toggleAutomationById(localStorage.token, automation.id));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const runHandler = async (automation: Automation) => {
		try {
			replace(await runAutomationById(localStorage.token, automation.id));
			toast.success($i18n.t('Automation started'));
			if (expandedId === automation.id) {
				runs = await getAutomationRuns(localStorage.token, automation.id);
			}
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const deleteHandler = async (automation: Automation) => {
		try {
			await deleteAutomationById(localStorage.token, automation.id);
			automations = (automations ?? []).filter((a) => a.id !== automation.id);
			toast.success($i18n.t('Automation deleted'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const toggleExpanded = async (automation: Automation) => {
		if (expandedId === automation.id) {
			expandedId = null;
			runs = [];
			return;
		}
		expandedId = automation.id;
		runs = [];
		try {
			runs = await getAutomationRuns(localStorage.token, automation.id);
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const statusClass = (status?: string) =>
		status === 'success'
			? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
			: status === 'error'
				? 'bg-red-500/15 text-red-700 dark:text-red-300'
				: 'bg-amber-500/15 text-amber-700 dark:text-amber-300';

	onMount(async () => {
		const allowed =
			($config?.features?.enable_automations ?? true) &&
			($user?.role === 'admin' || ($user?.permissions?.features?.automations ?? true));
		if (!allowed) {
			goto('/');
			return;
		}
		await load();
	});

	onDestroy(() => clearInterval(pollTimer));
</script>

<svelte:head>
	<title>
		{$i18n.t('Automations')} | {$WEBUI_NAME}
	</title>
</svelte:head>

<AutomationModal bind:show={showModal} automation={editing} onSaved={replace} />

<ConfirmDialog
	bind:show={showDeleteConfirm}
	title={$i18n.t('Delete automation?')}
	message={$i18n.t('This deletes "{{name}}" and its run history. Chats it created are kept.', {
		name: deleting?.name ?? ''
	})}
	on:confirm={() => deleting && deleteHandler(deleting)}
/>

<div
	class=" flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
		? 'md:max-w-[calc(100%-260px)]'
		: ''} max-w-full"
>
	<nav class="   px-2.5 pt-1 backdrop-blur-xl w-full drag-region">
		<div class=" flex items-center">
			<div class="{$showSidebar ? 'md:hidden' : ''} flex flex-none items-center self-end">
				<button
					id="sidebar-toggle-button"
					class="cursor-pointer p-1.5 flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click={() => {
						showSidebar.set(!$showSidebar);
					}}
					aria-label="Toggle Sidebar"
				>
					<div class=" m-auto self-center">
						<MenuLines />
					</div>
				</button>
			</div>
		</div>
	</nav>

	<div class="flex-1 max-h-full overflow-y-auto px-4 md:px-6 pb-8">
		<div class="max-w-3xl mx-auto w-full">
			<div class="flex items-center justify-between mt-2 mb-1">
				<div>
					<div class="text-xl font-medium font-primary flex items-center gap-2">
						{$i18n.t('Automations')}
						<span class="text-lg font-medium text-gray-500 dark:text-gray-300">
							{automations?.length ?? ''}
						</span>
					</div>
					<div class="text-xs text-gray-500">
						{$i18n.t('Let a model run a prompt for you on a schedule.')}
					</div>
				</div>

				<button
					class="px-3 py-1.5 rounded-xl bg-black text-white dark:bg-white dark:text-black transition font-medium text-sm flex items-center gap-1"
					on:click={() => {
						editing = null;
						showModal = true;
					}}
				>
					<Plus className="size-3.5" strokeWidth="2.5" />
					{$i18n.t('New')}
				</button>
			</div>

			{#if automations === null}
				<div class="flex justify-center py-16"><Spinner /></div>
			{:else if automations.length === 0}
				<div class="flex flex-col items-center text-center py-16 text-gray-500">
					<Clock className="size-10 mb-3" />
					<div class="font-medium text-gray-800 dark:text-gray-200">
						{$i18n.t('No automations yet')}
					</div>
					<div class="text-sm mt-1 max-w-sm">
						{$i18n.t(
							'Try "Every weekday at 8:00, summarize the top tech news" or "Every Friday, suggest a dinner plan for the weekend".'
						)}
					</div>
				</div>
			{:else}
				<div class="flex flex-col mt-3 gap-2">
					{#each automations as automation (automation.id)}
						<div
							class="rounded-2xl border border-gray-100 dark:border-gray-850 px-4 py-3 {automation.enabled
								? ''
								: 'opacity-60'}"
						>
							<div class="flex items-start gap-3">
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2">
										<div class="font-medium truncate">{automation.name}</div>
										{#if automation.last_run}
											<a
												class="text-[11px] px-1.5 py-0.5 rounded-md shrink-0 {statusClass(
													automation.last_run.status
												)}"
												href={automation.last_run.chat_id
													? `/c/${automation.last_run.chat_id}`
													: undefined}
												title={automation.last_run.error ?? ''}
											>
												{automation.last_run.status === 'running'
													? $i18n.t('Running…')
													: automation.last_run.status === 'success'
														? $i18n.t('Last run OK')
														: $i18n.t('Last run failed')}
											</a>
										{/if}
									</div>

									<div class="text-xs text-gray-500 mt-0.5 line-clamp-1">
										{automation.prompt}
									</div>

									<div class="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-gray-500 mt-1.5">
										<span class="flex items-center gap-1">
											<Clock className="size-3.5" />
											{describeSchedule(automation.options?.schedule, automation.rrule)}
										</span>
										<span>{modelName(automation.model_id)}</span>
										{#if automation.options?.web_search}
											<span>{$i18n.t('Web search')}</span>
										{/if}
										<span>
											{#if automation.enabled && automation.next_run_at}
												{$i18n.t('Next')}:
												<Tooltip
													content={dayjs(automation.next_run_at * 1000).format(
														'dddd D MMMM YYYY, HH:mm'
													)}
													className="inline"
												>
													{dayjs(automation.next_run_at * 1000).fromNow()}
												</Tooltip>
											{:else if automation.enabled}
												{$i18n.t('Finished')}
											{:else}
												{$i18n.t('Paused')}
											{/if}
										</span>
									</div>
								</div>

								<div class="flex items-center gap-0.5 shrink-0">
									<Tooltip content={$i18n.t('Run now')}>
										<button
											class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition"
											aria-label={$i18n.t('Run now')}
											on:click={() => runHandler(automation)}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												viewBox="0 0 20 20"
												fill="currentColor"
												class="size-4"
											>
												<path
													d="M6.3 2.84A1.5 1.5 0 0 0 4 4.11v11.78a1.5 1.5 0 0 0 2.3 1.27l9.344-5.891a1.5 1.5 0 0 0 0-2.538L6.3 2.841Z"
												/>
											</svg>
										</button>
									</Tooltip>
									<Tooltip content={$i18n.t('Edit')}>
										<button
											class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition"
											aria-label={$i18n.t('Edit')}
											on:click={() => {
												editing = automation;
												showModal = true;
											}}
										>
											<Pencil className="size-4" />
										</button>
									</Tooltip>
									<Tooltip content={$i18n.t('Delete')}>
										<button
											class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition"
											aria-label={$i18n.t('Delete')}
											on:click={() => {
												deleting = automation;
												showDeleteConfirm = true;
											}}
										>
											<GarbageBin className="size-4" />
										</button>
									</Tooltip>
									<Tooltip content={automation.enabled ? $i18n.t('Pause') : $i18n.t('Resume')}>
										<button
											role="switch"
											aria-checked={automation.enabled}
											aria-label={automation.enabled ? $i18n.t('Pause') : $i18n.t('Resume')}
											class="ml-1 flex h-5 w-9 items-center rounded-full px-[3px] transition outline outline-1 outline-gray-100 dark:outline-gray-800 {automation.enabled
												? 'bg-emerald-600'
												: 'bg-gray-200 dark:bg-transparent'}"
											on:click={() => toggleHandler(automation)}
										>
											<span
												class="block size-4 rounded-full bg-white transition-transform {automation.enabled
													? 'translate-x-3.5'
													: ''}"
											/>
										</button>
									</Tooltip>
								</div>
							</div>

							<button
								class="mt-2 text-xs text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 flex items-center gap-1"
								on:click={() => toggleExpanded(automation)}
							>
								{#if expandedId === automation.id}
									<ChevronUp className="size-3" />
								{:else}
									<ChevronDown className="size-3" />
								{/if}
								{$i18n.t('Run history')} ({automation.run_count})
							</button>

							{#if expandedId === automation.id}
								<div class="mt-2 flex flex-col text-xs">
									{#if runs.length === 0}
										<div class="text-gray-500 py-1">{$i18n.t('No runs yet')}</div>
									{/if}
									{#each runs as run (run.id)}
										<div
											class="flex items-center gap-2 py-1.5 border-t border-gray-50 dark:border-gray-850"
										>
											<span class="px-1.5 py-0.5 rounded-md {statusClass(run.status)}">
												{run.status}
											</span>
											<span class="text-gray-600 dark:text-gray-300">
												{dayjs(run.started_at * 1000).format('ddd D MMM, HH:mm')}
											</span>
											<span class="text-gray-400">
												{run.trigger === 'manual' ? $i18n.t('manual') : $i18n.t('scheduled')}
												{#if run.finished_at}
													· {run.finished_at - run.started_at}s
												{/if}
											</span>
											{#if run.error}
												<span class="text-red-500 truncate flex-1" title={run.error}>
													{run.error}
												</span>
											{:else}
												<span class="flex-1" />
											{/if}
											{#if run.chat_id}
												<a class="underline shrink-0" href={`/c/${run.chat_id}`}>
													{$i18n.t('Open chat')}
												</a>
											{/if}
										</div>
									{/each}
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</div>
</div>
