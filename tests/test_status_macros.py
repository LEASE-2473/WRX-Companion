import pytest
from app.models import ChatMessage, Lorebook, PromptEntry, PromptOrderEntry
from app.prompt_store import default_wrx_preset
from app.prompt_compiler import compile_prompt


def compile(preset, images=None):
    return compile_prompt(preset, Lorebook(id='empty', name='空'), 2,
                          [ChatMessage(role='user', content='历史问题'), ChatMessage(role='assistant', content='历史回复')],
                          '本轮问题', current_images=images, char_status='状态快照', char_status_rules='情绪规则')


def add(preset, entry, before=False):
    preset.prompts.append(entry)
    order = PromptOrderEntry(identifier=entry.identifier)
    if before:
        i = next(i for i, p in enumerate(preset.prompt_order) if p.identifier == 'chatHistory')
        preset.prompt_order.insert(i, order)
    else:
        preset.prompt_order.append(order)


def test_default_rules_before_history_status_at_d1_and_user_last():
    result = compile(default_wrx_preset(), ['data:image/png;base64,iVBORw0KGgo='])
    texts = [m.content for m in result.messages]
    assert texts.index('情绪规则') < texts.index('历史问题')
    assert result.messages[-2].content == '状态快照'
    assert result.messages[-1].role == 'user'
    assert result.messages[-1].content == '本轮问题'
    assert result.messages[-1].images == ['data:image/png;base64,iVBORw0KGgo=']
    assert result.trace['final_messages'] == [m.model_dump() for m in result.messages]
    for injection in result.trace['in_chat']:
        assert result.messages[injection['actual_message_index']].content == '状态快照'


@pytest.mark.parametrize('position,depth', [('relative', 0), ('in_chat', 0), ('in_chat', 2)])
def test_enabled_macros_replace_fallback_and_obey_preset_position(position, depth):
    preset = default_wrx_preset()
    add(preset, PromptEntry(identifier='custom-status', name='状态', content='{{ CHAR_STATUS }} / {{char_status_rules}}',
                            injection_position=position, injection_depth=depth), before=True)
    result = compile(preset)
    combined = '\n'.join(m.content for m in result.messages)
    assert combined.count('状态快照') == 1
    assert combined.count('情绪规则') == 1
    assert '{{' not in combined
    assert result.messages[-1].content == '本轮问题'
    if position == 'relative':
        assert combined.index('状态快照') < combined.index('历史问题')
    for injection in result.trace['in_chat']:
        assert '状态快照' in result.messages[injection['actual_message_index']].content


def test_disabled_macro_does_not_remove_default_injection():
    preset = default_wrx_preset()
    add(preset, PromptEntry(identifier='disabled', name='禁用', enabled=False, content='{{char_status}} {{char_status_rules}}'))
    texts = [m.content for m in compile(preset).messages]
    assert texts.count('状态快照') == 1
    assert texts.count('情绪规则') == 1


def test_tail_self_check_stays_system_before_current_user():
    preset = default_wrx_preset()
    add(preset, PromptEntry(identifier='self-check', name='自检', content='回复自检'))
    result = compile(preset)
    assert result.messages[-1].role == 'user'
    assert result.messages[-1].content == '本轮问题'
    assert result.messages[-2].role == 'system'
    assert result.messages[-2].content == '状态快照'
    assert next(m for m in result.messages if m.content == '回复自检').role == 'system'


def test_time_and_status_share_d1_without_contaminating_user():
    result = compile_prompt(default_wrx_preset(), Lorebook(id='empty', name='空'), 0, [],
                            '实际正文', char_status='当前状态', char_status_rules='固定规则', current_time='服务器时间')
    assert result.messages[-2].role == 'system'
    assert result.messages[-2].content == '当前状态\n\n服务器时间'
    assert result.messages[-1].content == '实际正文'


def test_current_time_macro_replaces_default_time_injection():
    preset = default_wrx_preset()
    add(preset, PromptEntry(identifier='time', name='时间', content='{{current_time}}', injection_position='in_chat', injection_depth=1))
    result = compile_prompt(preset, Lorebook(id='empty', name='空'), 0, [], '实际正文', current_time='服务器时间')
    assert sum('服务器时间' in m.content for m in result.messages) == 1
    assert result.messages[-2].content == '服务器时间'
    assert result.messages[-1].content == '实际正文'
