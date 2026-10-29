<script lang="ts">
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import { getContext } from 'svelte';

	import { config, models, user } from '$lib/stores';
	import {
		createAutomation,
		previewSchedule,
		updateAutomationById,
		type Automation
	} from '$lib/apis/automations';
	import {
		WEEKDAYS,
		browserTimezone,
		defaultSchedule,
		toRule,
		type Schedule,
		type ScheduleType
	} from './schedule';

	import Modal from '$lib/components/common/Modal.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const i18n = getContext('i18n');

	export let show = false;
	export let automation: Automation | null = null;
	export let onSaved: (automation: Automation) => void = () => {};

	let name = '';
	let prompt = '';
	let modelId = '';
	let webSearch = false;
	let enabled = true;
	let schedule: Schedule = defaultSchedule();
	let timezone = browserTimezone();

	let loading = false;
	let preview: number[] = [];
	let previewError = '';
	let previewTimer: ReturnType<typeof setTimeout> | undefined;
	let previewSeq = 0;

	$: selectableModels = ($models ?? []).filter((m) => !(m?.info?.meta?.hidden ?? false));
	$: canWebSearch =
		($config?.features?.enable_web_search ?? false) &&
		($user?.role === 'admin' || ($user?.permissions?.features?.web_search ?? true));

	const init = () => {
		if (automation) {
			name = automation.name;
			prompt = automation.prompt;
			modelId = automation.model_id;
			webSearch = automation.options?.web_search ?? false;
			enabled = automation.enabled;
			schedule = { ...defaultSchedule(), ...(automation.options?.schedule ?? {}) };
			// Keep the automation's own timezone unless this is a fresh pick.
			timezone = automation.timezone || browserTimezone();
			if (!automation.options?.schedule) {
				schedule = { ...schedule, type: 'custom', rrule: automation.rrule };
			}
		} else {
			name = '';
			prompt = '';
			modelId = selectableModels[0]?.id ?? '';
			webSearch = false;
			enabled = true;
			schedule = defaultSchedule();
			timezone = browserTimezone();
		}
	};

	let initializedFor: string | null | undefined = undefined;
	$: if (show && initializedFor !== (automation?.id ?? null)) {
		initializedFor = automation?.id ?? null;
		init();
	}
	$: if (!show) {
		initializedFor = undefined;
	}

	const refreshPreview = (s: Schedule) => {
		clearTimeout(previewTimer);
		previewTimer = setTimeout(async () => {
			const rule = toRule(s);
			const seq = ++previewSeq;
			try {
				const res = await previewSchedule(localStorage.token, {
					...rule,
					timezone: browserTimezone()
				});
				if (seq !== previewSeq) return;
				preview = res.occurrences.slice(0, 3);
				previewError = '';
			} catch (error) {
				if (seq !== previewSeq) return;
				preview = [];
				previewError = `${error}`;
			}
		}, 300);
	};

	$: if (show) refreshPreview(schedule);

	const toggleDay = (code: string) => {
		schedule.days = schedule.days.includes(code)
			? schedule.days.filter((d) => d !== code)
			: [...schedule.days, code];
	};

	const submitHandler = async () => {
		if (!modelId) {
			toast.error($i18n.t('Please select a model.'));
			return;
		}

		loading = true;
		// The picker works in the browser's wall clock, so a saved schedule
		// moves to the browser timezone whenever it is edited here.
		timezone = browserTimezone();
		const form = {
			name: name.trim(),
			prompt,
			model_id: modelId,
			...toRule(schedule),
			timezone,
			enabled,
			options: {
				...(automation?.options ?? {}),
				web_search: canWebSearch && webSearch,
				schedule
			}
		};

		try {
			const saved = automation
				? await updateAutomationById(localStorage.token, automation.id, form)
				: await createAutomation(localStorage.token, form);
			toast.success(automation ? $i18n.t('Automation updated') : $i18n.t('Automation created'));
			onSaved(saved);
			show = false;
		} catch (error) {
			toast.error(`${error}`);
		}
		loading = false;
	};

	const SCHEDULE_TYPES: [ScheduleType, string][] = [
		['once', 'Once'],
		['hourly', 'Hourly'],
		['daily', 'Daily'],
		['weekly', 'Weekly'],
		['monthly', 'Monthly'],
		['custom', 'Custom']
	];

	const inputClass =
		'w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-hidden';
	const selectClass =
		'dark:bg-gray-900 rounded-lg py-1.5 px-2 text-sm bg-gray-50 outline-hidden border border-gray-100 dark:border-gray-850';
</script>

<Modal size="md" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-100 px-5 pt-4 mb-1.5">
			<div class=" text-lg font-medium self-center font-primary">
				{automation ? $i18n.t('Edit Automation') : $i18n.t('New Automation')}
			</div>
			<button
				class="self-center"
				aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<XMark className="size-5" />
			</button>
		</div>

		<form
			class="flex flex-col w-full px-5 pb-4 dark:text-gray-200"
			on:submit|preventDefault={submitHandler}
		>
			<div class="flex flex-col w-full">
				<div class=" mb-0.5 text-xs text-gray-500">{$i18n.t('Name')}</div>
				<input
					class={inputClass}
					type="text"
					bind:value={name}
					placeholder={$i18n.t('e.g. Morning news digest')}
					autocomplete="off"
					required
				/>
			</div>

			<div class="flex flex-col w-full mt-3">
				<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Prompt')}</div>
				<Textarea
					className="{inputClass} resize-none"
					rows={4}
					bind:value={prompt}
					placeholder={$i18n.t('What should the model do each time this runs?')}
					required
				/>
			</div>

			<div class="flex flex-col w-full mt-3">
				<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Model')}</div>
				<select class="{selectClass} w-full" bind:value={modelId} required>
					<option value="" disabled>{$i18n.t('Select a model')}</option>
					{#each selectableModels as model (model.id)}
						<option value={model.id}>{model.name ?? model.id}</option>
					{/each}
				</select>
			</div>

			<hr class="border-gray-100 dark:border-gray-850 my-4" />

			<div class="flex flex-col w-full">
				<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Schedule')}</div>

				<div class="flex flex-wrap gap-1">
					{#each SCHEDULE_TYPES as [value, label]}
						<button
							type="button"
							class="px-2.5 py-1 text-xs rounded-full transition {schedule.type === value
								? 'bg-gray-900 text-white dark:bg-white dark:text-black'
								: 'bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800'}"
							on:click={() => {
								schedule.type = value;
							}}
						>
							{$i18n.t(label)}
						</button>
					{/each}
				</div>

				<div class="flex flex-wrap items-center gap-2 mt-3 text-sm">
					{#if schedule.type === 'once'}
						<span class="text-gray-500 text-xs">{$i18n.t('On')}</span>
						<input class={selectClass} type="date" bind:value={schedule.date} required />
					{:else if schedule.type === 'hourly'}
						<span class="text-gray-500 text-xs">{$i18n.t('Every')}</span>
						<input
							class="{selectClass} w-16"
							type="number"
							min="1"
							max="23"
							bind:value={schedule.hours}
							required
						/>
						<span class="text-gray-500 text-xs">{$i18n.t('hours, starting')}</span>
					{:else if schedule.type === 'weekly'}
						<div class="flex gap-1">
							{#each WEEKDAYS as day}
								<button
									type="button"
									class="w-9 py-1 text-xs rounded-lg transition {schedule.days.includes(day.code)
										? 'bg-gray-900 text-white dark:bg-white dark:text-black'
										: 'bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800'}"
									on:click={() => toggleDay(day.code)}
								>
									{$i18n.t(day.label)}
								</button>
							{/each}
						</div>
					{:else if schedule.type === 'monthly'}
						<span class="text-gray-500 text-xs">{$i18n.t('On day')}</span>
						<input
							class="{selectClass} w-16"
							type="number"
							min="1"
							max="31"
							bind:value={schedule.monthday}
							required
						/>
					{:else if schedule.type === 'custom'}
						<input
							class="{selectClass} flex-1 font-mono text-xs"
							type="text"
							bind:value={schedule.rrule}
							placeholder="FREQ=WEEKLY;BYDAY=MO,WE;INTERVAL=2"
							required
						/>
						<span class="text-gray-500 text-xs">{$i18n.t('starting')}</span>
					{/if}

					<span class="text-gray-500 text-xs">{$i18n.t('at')}</span>
					<input class={selectClass} type="time" bind:value={schedule.time} required />
				</div>

				<div class="mt-2 text-xs">
					{#if previewError}
						<span class="text-red-500">{previewError}</span>
					{:else if preview.length}
						<span class="text-gray-500">{$i18n.t('Next runs')}:</span>
						<span class="text-gray-700 dark:text-gray-300">
							{preview.map((t) => dayjs(t * 1000).format('ddd D MMM, HH:mm')).join(' · ')}
						</span>
						<span class="text-gray-400">({browserTimezone()})</span>
					{/if}
				</div>
			</div>

			<hr class="border-gray-100 dark:border-gray-850 my-4" />

			<div class="flex flex-col gap-2 text-sm">
				{#if canWebSearch}
					<label class="flex items-center justify-between cursor-pointer">
						<span>{$i18n.t('Search the web on each run')}</span>
						<input type="checkbox" class="size-4 accent-gray-900" bind:checked={webSearch} />
					</label>
				{/if}
				<label class="flex items-center justify-between cursor-pointer">
					<span>{$i18n.t('Enabled')}</span>
					<input type="checkbox" class="size-4 accent-gray-900" bind:checked={enabled} />
				</label>
				<div class="text-xs text-gray-500">
					{$i18n.t(
						'Each run creates a new chat in your "Automations" folder and sends you a notification.'
					)}
				</div>
			</div>

			<div class="flex justify-end pt-4 text-sm font-medium gap-1.5">
				<button
					class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full flex flex-row space-x-1 items-center {loading
						? ' cursor-not-allowed'
						: ''}"
					type="submit"
					disabled={loading || !!previewError}
				>
					{automation ? $i18n.t('Save') : $i18n.t('Create')}
					{#if loading}
						<div class="ml-2 self-center"><Spinner className="size-4" /></div>
					{/if}
				</button>
			</div>
		</form>
	</div>
</Modal>
