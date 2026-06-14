// static/js/main.js - 最终修复版 (完整代码)

// =======================
// == 0. 安全与工具函数 (必须放在最顶部)
// =======================

/**
 * XSS 防御：转义 HTML 字符
 */
function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const str = String(text);
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


// =======================
// == 页面加载主逻辑
// =======================
document.addEventListener('DOMContentLoaded', () => {
    console.log("DOM完全加载，开始执行JS。");
    const body = document.body;
    const pageRoot = document.querySelector('[data-page-id]');
    const pageId = body.dataset.pageId || (pageRoot ? pageRoot.dataset.pageId : undefined);
    const mainContent = document.getElementById('main-content-wrapper'); // 在顶层获取

    console.log(`检测到页面ID: ${pageId}`);

    // 页面初始化函数映射表 (保持不变)
    const initializers = {
        'dashboard': initializeDashboard,
        'guild': initializeGuildPage,
        'settings': initializeSettingsPage,
        'moderation': initializeModerationPage,
        'announcements': initializeAnnouncementsPage,
        'channel_control': initializeChannelControlPage,
        'audit_core': initializeAuditCorePage,
        'warnings': initializeWarningsPage,
        'permissions': initializePermissionsPage,
        'superuser_accounts': initializeSuperuserAccountsPage,
        'bot_profile': initializeBotProfilePage,
        'backup': initializeBackupPage,
        'superuser_broadcast': initializeSuperuserBroadcastPage,
        'music_control': initializeMusicControlPage,
    };
    
    // 【核心修复】全局内容可见性处理
    if (pageId === 'dashboard' && !sessionStorage.getItem('welcomeShown')) {
        // 如果是首次访问仪表盘，则不立即显示内容，
        // 将由 initializeDashboard 中的动画来控制内容的最终显示。
        console.log("首次访问Dashboard，将由动画控制内容显示。");
    } else {
        // 对于所有其他页面，或者非首次访问仪表盘，立即显示内容。
        if (mainContent) {
            mainContent.classList.remove('content-hidden');
            mainContent.classList.add('content-visible');
            console.log("立即显示页面内容。");
        }
    }

    // 执行当前页面专属的初始化函数
    if (initializers[pageId]) {
        console.log(`初始化页面: ${pageId}...`);
        initializers[pageId]();
    } else if (pageId !== 'tickets') { // tickets 页面有自己的内联脚本
        console.warn(`未找到页面标识符 (data-page-id: ${pageId})，不执行任何页面专属初始化。`);
    }
});


// =======================
// == 通用功能函数 (保持不变)
// =======================
async function apiRequest(endpoint, options = {}) {
    try {
        // 【新增】获取 HTML 头部的 CSRF Token
        const metaTag = document.querySelector('meta[name="csrf-token"]');
        const csrfToken = metaTag ? metaTag.getAttribute('content') : null;
        
        // 确保 headers 对象存在
        options.headers = options.headers || {};
        
        // 【新增】自动携带 Token
        if (csrfToken) {
            options.headers['X-CSRFToken'] = csrfToken;
        }

        const response = await fetch(endpoint, options);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: `HTTP 错误: ${response.status}` }));
            
            // 【新增】Token 失效时强制刷新
            if (response.status === 400 && (errorData.message.includes('CSRF') || errorData.message.includes('session'))) {
                alert("会话已过期或验证失败，请刷新页面重试。");
                location.reload();
                throw new Error("CSRF Token 失效");
            }
            throw new Error(errorData.message || `HTTP 错误: ${response.status}`);
        }
        if (response.status === 204) return { status: 'success', message: '操作成功' };
        return await response.json();
    } catch (error) {
        console.error(`请求失败 [${endpoint}]:`, error);
        if (!options.silent) alert(`操作失败: ${error.message}`);
        throw error;
    }
}

function setupCommonEventListeners(GUILD_ID, renderers = {}) {
    console.log(`[setupEventListeners] 为服务器/全局绑定通用事件...`);
    const body = document.body;
    if (body.clickListener) body.removeEventListener('click', body.clickListener);
    if (body.submitListener) body.removeEventListener('submit', body.submitListener);
    const clickListener = (event) => {
        const button = event.target.closest('.action-btn');
        if (button && GUILD_ID) {
            if (document.body.dataset.pageId === 'audit_core') return;
            event.preventDefault();
            handleAction(button, GUILD_ID, renderers);
        }
    };
    const submitListener = async (event) => {
        if (event.target.tagName !== 'FORM' || ['ticket-reply-form', 'permission-group-form', 'sub-account-form', 'exempt-user-form', 'exempt-channel-form', 'role-editor-form', 'department-form'].includes(event.target.id)) return;
        event.preventDefault();
        const form = event.target;
        const formData = new FormData(form);
        let payload = Object.fromEntries(formData.entries());
        payload.form_id = form.id;
        const endpoint = `/api/guild/${GUILD_ID}/form_submit`;
        if (form.id === 'mute-form') { payload.target_id = payload.user_id; delete payload.user_id; }
        if (form.id === 'balance-form' && event.submitter) { payload.sub_action = event.submitter.dataset.action; }
        if (form.id === 'edit-item-form') { payload.action = form.querySelector('#item_slug').value ? "edit" : "add"; }
        if (['kb-add-form', 'faq-add-form', 'bot-whitelist-form', 'ai-dep-form'].includes(form.id)) { payload.action = 'add'; }
        const multiSelects = form.querySelectorAll("[multiple]");
        multiSelects.forEach(select => { payload[select.name] = Array.from(new FormData(form).getAll(select.name)); });
        try {
            const data = await apiRequest(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            alert(data.message);
            if (data.status === "success") {
                const modal = form.closest('.modal');
                if (modal && bootstrap.Modal.getInstance(modal)) bootstrap.Modal.getInstance(modal).hide();
                form.reset();
                location.reload(); 
            }
        } catch (error) {}
    };
    body.addEventListener('click', clickListener);
    body.addEventListener('submit', submitListener);
    body.clickListener = clickListener;
    body.submitListener = submitListener;
}


// =======================
// == 页面初始化函数
// =======================

function initializeDashboard() {
    // 【核心修复】此函数现在只处理动画和仪表盘专属的统计数据获取

    const welcomeOverlay = document.getElementById('welcome-overlay');
    const mainContent = document.getElementById('main-content-wrapper');
    const welcomeTextMain = document.getElementById('welcome-text-main');
    const welcomeTextSub = document.getElementById('welcome-text-sub');

    // 动画逻辑只在需要时执行
    if (welcomeOverlay && mainContent && welcomeTextMain && welcomeTextSub && !sessionStorage.getItem('welcomeShown')) {
        const messages = [
            { main: "正在验证身份...", sub: "Connecting to authentication server..." },
            { main: "欢迎, 管理员", sub: "Welcome, Administrator" },
            { main: "Glitch God 控制台", sub: "Initializing Control Panel..." },
            { main: "系统准备就绪", sub: "All systems nominal. Welcome." }
        ];

        let messageIndex = 0;
        
        const typeMessage = (element, text, callback) => {
            let i = 0;
            element.textContent = '';
            const typing = setInterval(() => {
                if (i < text.length) {
                    element.textContent += text.charAt(i);
                    i++;
                } else {
                    clearInterval(typing);
                    if (callback) callback();
                }
            }, 60);
        };

        const showNextMessage = () => {
            if (messageIndex < messages.length) {
                typeMessage(welcomeTextMain, messages[messageIndex].main);
                setTimeout(() => {
                    typeMessage(welcomeTextSub, messages[messageIndex].sub, () => {
                        if (messageIndex < messages.length - 1) {
                            setTimeout(showNextMessage, 1200);
                        } else {
                            setTimeout(endWelcomeAnimation, 1500);
                        }
                    });
                }, 500);
                messageIndex++;
            }
        };

        const endWelcomeAnimation = () => {
            welcomeOverlay.classList.add('fade-out');
            mainContent.classList.remove('content-hidden');
            mainContent.classList.add('content-visible');
            welcomeOverlay.addEventListener('transitionend', () => {
                welcomeOverlay.style.display = 'none';
            }, { once: true });
        };

        welcomeOverlay.classList.add('visible');
        setTimeout(showNextMessage, 500);
        sessionStorage.setItem('welcomeShown', 'true');
    } 
    // 【核心修复】移除了这里的 else 块，因为全局逻辑已经处理了非首次访问的情况。
    
    // 仪表盘专属的统计数据获取逻辑 (保持不变)
    const statsElements = { guilds: document.getElementById('guild-count'), users: document.getElementById('user-count'), latency: document.getElementById('latency'), commands: document.getElementById('command-count') };
    const fetchStats = async () => { try { const data = await apiRequest('/api/stats'); if (data) Object.keys(statsElements).forEach(key => { if (statsElements[key]) statsElements[key].textContent = data[key] + (key === 'latency' ? ' ms' : ''); }); } catch (e) {} };
    document.getElementById('guild-select-form')?.addEventListener('submit', (e) => { e.preventDefault(); const id = document.getElementById('guild-selector').value; if (id) window.location.href = `/guild/${id}`; });
    fetchStats(); 
    setInterval(fetchStats, 20000);
}

// 其他所有页面的 initialize... 函数保持不变
function initializeGuildPage() {
    const GUILD_ID = document.body.dataset.guildId;
    if (!GUILD_ID) return;
    let economyChart = null;
    function applyTabPermissions() {
        const managementTabs = document.getElementById('managementTabs');
        const managementPanes = document.getElementById('managementTabsContent');
        if (!managementTabs || !managementPanes) return;

        const userPermsJson = document.getElementById('user-permissions-data')?.textContent;
        if (!userPermsJson) {
            console.warn("未找到用户权限数据，将显示所有标签页作为后备。");
            return;
        }

        const userPerms = JSON.parse(userPermsJson);
        const tabItems = managementTabs.querySelectorAll('.nav-item');
        let firstVisibleTabToActivate = null;

        // 1. 根据权限显示或隐藏每个标签项，并找出第一个可以被激活的标签
        tabItems.forEach(item => {
            const perm = item.dataset.permission;
            if (perm && userPerms.includes(perm)) {
                item.style.display = ''; // 显示有权限的项
                
                // 寻找第一个可激活的 *按钮*
                if (!firstVisibleTabToActivate) {
                    const button = item.querySelector('button.nav-link[data-bs-toggle="tab"]');
                    if (button) {
                        firstVisibleTabToActivate = button;
                    }
                }
            } else {
                item.style.display = 'none'; // 隐藏无权限的项
            }
        });
        
        // 2. 如果找到了第一个可见的、可激活的标签页，就激活它
        if (firstVisibleTabToActivate) {
            const tab = new bootstrap.Tab(firstVisibleTabToActivate);
            tab.show(); // 使用 Bootstrap 的 API 来正确显示标签和其对应的内容面板
        } else {
            // 如果一个可激活的标签页都找不到（例如用户只有一个外部链接的权限），
            // 确保没有任何内容面板是激活的。
            managementPanes.querySelectorAll('.tab-pane').forEach(pane => {
                pane.classList.remove('show', 'active');
            });
        }

        // 3. 特殊处理“票据”这类外部链接，如果当前就在那个页面，则给它 'active' 样式
        const ticketsLinkItem = managementTabs.querySelector('[data-permission="tab_tickets"]');
        if (ticketsLinkItem && ticketsLinkItem.style.display !== 'none') {
            const link = ticketsLinkItem.querySelector('a.nav-link');
            if (link && window.location.pathname.includes('/tickets')) {
                link.classList.add('active');
            }
        }
    }
    const renderers = {
        shop: (data) => {
            const tbody = document.getElementById('shop-items-table'); if (!tbody) return;
            tbody.innerHTML = !data.items?.length ? '<tr><td colspan="4" class="text-center text-muted">商店是空的。</td></tr>' : data.items.map(item => `<tr data-entity-id="${item.item_slug}"><td>${item.name}</td><td>${item.price}</td><td>${item.stock === -1 ? '无限' : item.stock}</td><td><div class="btn-group"><button class="btn btn-primary btn-sm" data-bs-toggle="modal" data-bs-target="#editItemModal" data-item-data='${JSON.stringify(item)}'>编辑</button><button class="btn btn-danger btn-sm action-btn" data-action="shop/action" data-target-id="${item.item_slug}" data-sub-action="delete">删除</button></div></td></tr>`).join('');
        },
        kb: (data) => {
            const list = document.getElementById('kb-list'); if(!list) return;
            list.innerHTML = !data.kb?.length 
                ? '<li class="list-group-item text-muted">知识库是空的。</li>' 
                : data.kb.map((entry, index) => `
                    <li class="list-group-item d-flex justify-content-between align-items-center" data-entity-id="${index + 1}">
                        <span class="kb-entry-text" title='${entry.replace(/'/g, "\\'")}'>${entry.substring(0, 80)}...</span>
                        
                        <!-- 【核心修复】修改了 data-action，移除了 data-sub-action -->
                        <button class="btn btn-danger btn-sm action-btn" data-action="action/kb_remove" data-target-id="${index + 1}">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </li>`).join('');
        },
        faq: (data) => {
            const accordion = document.getElementById('faq-accordion'); if (!accordion) return;
            accordion.innerHTML = !data.faq || !Object.keys(data.faq).length ? '<p class="text-muted mt-2">FAQ是空的。</p>' : Object.entries(data.faq).map(([kw, ans], i) => `<div class="accordion-item" data-entity-id="${kw}"><h2 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#faq-${i}"><strong>${kw}</strong></button></h2><div id="faq-${i}" class="accordion-collapse collapse" data-bs-parent="#faq-accordion"><div class="accordion-body"><p>${ans.replace(/\n/g,"<br>")}</p><hr><button class="btn btn-danger btn-sm action-btn" data-action="data/faq" data-target-id="${kw}" data-sub-action="remove">删除</button></div></div></div>`).join('');
        },
        economy_stats: (data) => {
            if (!data.stats) return;
            const stats = data.stats;
            document.getElementById('total-currency-stat').textContent = stats.total_currency.toLocaleString();
            document.getElementById('economy-user-count-stat').textContent = stats.user_count.toLocaleString();
            const ctx = document.getElementById('economy-leaderboard-chart')?.getContext('2d');
            if (!ctx) return;
            const labels = stats.top_users.map(u => u.username);
            const balances = stats.top_users.map(u => u.balance);
            if (economyChart) economyChart.destroy();
            economyChart = new Chart(ctx, {
                type: 'bar',
                data: { labels, datasets: [{ label: '金币余额', data: balances, backgroundColor: 'rgba(255, 193, 7, 0.5)', borderColor: 'rgba(255, 193, 7, 1)', borderWidth: 1 }] },
                options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } }, plugins: { legend: { display: false } } }
            });
        }
    };
    const loadAllData = async () => { 
        try { 
            await Promise.all([ 
                apiRequest(`/api/guild/${GUILD_ID}/shop/items`).then(renderers.shop), 
                apiRequest(`/api/guild/${GUILD_ID}/data/kb`).then(renderers.kb), 
                apiRequest(`/api/guild/${GUILD_ID}/data/faq`).then(renderers.faq), 
                apiRequest(`/api/guild/${GUILD_ID}/economy_stats`).then(renderers.economy_stats)
            ]); 
        } catch (error) { console.error("加载页面数据时出错:", error); } 
    };
    setupCommonEventListeners(GUILD_ID, renderers);
    document.getElementById('roleModal')?.addEventListener('show.bs.modal', async (event) => {
        const button = event.relatedTarget; if (!button) return;
        const memberId = button.dataset.memberId; const memberName = button.dataset.memberName;
        document.getElementById('role-modal-member-id').value = memberId;
        document.getElementById('role-modal-username').textContent = memberName;
        const form = document.getElementById('member-roles-form'); form.reset();
        const giveSelect = form.querySelector('select[name="roles_to_give"]');
        const takeSelect = form.querySelector('select[name="roles_to_take"]');
        const allRoleOptionsSource = document.getElementById('guild-page-all-roles-source');
        if (!allRoleOptionsSource) { console.error("未能找到身份组数据源 #guild-page-all-roles-source"); return; }
        const allRoleOptions = Array.from(allRoleOptionsSource.options);
        giveSelect.innerHTML = '';
        allRoleOptions.forEach(opt => giveSelect.appendChild(opt.cloneNode(true)));
        takeSelect.innerHTML = '<option disabled>正在加载...</option>';
        try {
            const data = await apiRequest(`/api/guild/${GUILD_ID}/member/${memberId}/roles`);
            takeSelect.innerHTML = '';
            if (data.status === 'success' && Array.isArray(data.roles)) {
                if (data.roles.length === 0) { takeSelect.innerHTML = '<option disabled>该成员没有可移除的身份组</option>'; } 
                else { 
                    data.roles.forEach(roleId => { 
                        const optionNode = allRoleOptions.find(opt => opt.value === roleId);
                        if (optionNode) {
                            takeSelect.appendChild(optionNode.cloneNode(true));
                            const giveOption = giveSelect.querySelector(`option[value="${roleId}"]`);
                            if(giveOption) giveOption.remove();
                        }
                    });
                }
            } else { takeSelect.innerHTML = `<option disabled>加载身份组失败</option>`; }
        } catch (error) { takeSelect.innerHTML = '<option disabled>加载身份组时出错</option>'; }
    });
    document.getElementById('editItemModal')?.addEventListener('show.bs.modal', (event) => {
        const button = event.relatedTarget; const form = document.getElementById('edit-item-form'); form.reset();
        const isNew = button.dataset.itemIsNew === 'true';
        if (isNew) {
            document.getElementById('editItemModalLabel').textContent = '添加新物品';
            form.querySelector('#item_slug').value = '';
            form.querySelector('#item_name').readOnly = false;
        } else {
            const item = JSON.parse(button.dataset.itemData);
            document.getElementById('editItemModalLabel').textContent = `编辑: ${item.name}`;
            form.querySelector('#item_slug').value = item.item_slug;
            form.querySelector('#item_name').value = item.name;
            form.querySelector('#item_name').readOnly = true;
            form.querySelector('#item_price').value = item.price;
            form.querySelector('#item_stock').value = item.stock;
            form.querySelector('#item_description').value = item.description || '';
            form.querySelector('#item_role').value = item.role_id || '';
            form.querySelector('#item_purchase_message').value = item.purchase_message || '';
        }
    });
    const memberTableBody = document.getElementById('member-list-body');
    const selectAllCheckbox = document.getElementById('select-all-members');
    const toolbar = document.getElementById('bulk-actions-toolbar');
    const selectedCountSpan = document.getElementById('bulk-selected-count');
    function updateToolbar() {
        if (!memberTableBody || !toolbar || !selectedCountSpan) return;
        const selectedCheckboxes = memberTableBody.querySelectorAll('.member-checkbox:checked');
        const count = selectedCheckboxes.length;
        selectedCountSpan.textContent = count;
        toolbar.style.display = count > 0 ? 'inline-block' : 'none';
        if (selectAllCheckbox) {
            selectAllCheckbox.checked = count > 0 && count === memberTableBody.querySelectorAll('.member-checkbox').length;
            selectAllCheckbox.indeterminate = count > 0 && count < memberTableBody.querySelectorAll('.member-checkbox').length;
        }
    }
    if(selectAllCheckbox) selectAllCheckbox.addEventListener('change', () => {
        memberTableBody.querySelectorAll('.member-checkbox').forEach(cb => cb.checked = selectAllCheckbox.checked);
        updateToolbar();
    });
    if(memberTableBody) memberTableBody.addEventListener('change', (event) => { if (event.target.classList.contains('member-checkbox')) updateToolbar(); });
    async function handleBulkAction(action) {
        const selectedCheckboxes = Array.from(memberTableBody.querySelectorAll('.member-checkbox:checked'));
        const targetIds = selectedCheckboxes.map(cb => cb.value);
        if (targetIds.length === 0) { alert('请至少选择一个成员。'); return; }
        let roleId = null;
        if (action === 'bulk_add_role' || action === 'bulk_remove_role') {
            const actionText = action === 'bulk_add_role' ? '授予' : '移除';
            const allRoleOptionsSource = document.getElementById('guild-page-all-roles-source');
            if (!allRoleOptionsSource) { alert("错误：无法找到身份组列表。"); return; }
            const roleOptionsText = Array.from(allRoleOptionsSource.options).map((opt, index) => `${index + 1}: ${opt.textContent}`).join('\n');
            const roleIndexStr = prompt(`请为选中的 ${targetIds.length} 个成员选择要 ${actionText} 的身份组，输入序号：\n\n${roleOptionsText}`);
            if (roleIndexStr) {
                const roleIndex = parseInt(roleIndexStr, 10) - 1;
                const selectedOption = allRoleOptionsSource.options[roleIndex];
                if (selectedOption) { roleId = selectedOption.value; } else { alert('无效的序号。'); return; }
            } else { return; }
        } else if (action === 'bulk_kick') { if (!confirm(`你确定要踢出选中的 ${targetIds.length} 个成员吗？此操作不可逆！`)) return; }
        try {
            const data = await apiRequest(`/api/guild/${GUILD_ID}/bulk_action`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, target_ids: targetIds, role_id: roleId }) });
            alert(data.message);
            if (data.status === "success") {
                if (selectAllCheckbox) selectAllCheckbox.checked = false;
                memberTableBody.querySelectorAll('.member-checkbox:checked').forEach(cb => cb.checked = false);
                updateToolbar();
                location.reload(); 
            }
        } catch (error) {}
    }
    document.getElementById('bulk-add-role-btn')?.addEventListener('click', () => handleBulkAction('bulk_add_role'));
    document.getElementById('bulk-remove-role-btn')?.addEventListener('click', () => handleBulkAction('bulk_remove_role'));
    document.getElementById('bulk-kick-btn')?.addEventListener('click', () => handleBulkAction('bulk_kick'));
    const memberSearchInput = document.getElementById('member-search-input');
    if (memberSearchInput && memberTableBody) {
        memberSearchInput.addEventListener('input', () => {
            const searchTerm = memberSearchInput.value.toLowerCase().trim();
            const rows = memberTableBody.querySelectorAll('tr');
            rows.forEach(row => {
                const nameCell = row.cells[1];
                const idCell = row.cells[2];
                if (nameCell && idCell) {
                    const nameText = nameCell.textContent.toLowerCase();
                    const idText = idCell.textContent.toLowerCase();
                    if (nameText.includes(searchTerm) || idText.includes(searchTerm)) {
                        row.style.display = ''; 
                    } else {
                        row.style.display = 'none'; 
                    }
                }
            });
        });
    }

    loadAllData();
    applyTabPermissions();
    // --- 新的身份组编辑器逻辑 ---
    const roleEditorModal = new bootstrap.Modal(document.getElementById('role-editor-modal'));
    const roleEditorForm = document.getElementById('role-editor-form');
    const createRoleBtn = document.getElementById('create-new-role-btn');
    const roleTableBody = document.querySelector('#roles-tab-pane tbody');

    // 清理和重置表单
    const resetRoleEditorForm = () => {
        roleEditorForm.reset();
        document.getElementById('edit-role-id').value = '';
        document.getElementById('role-editor-title').textContent = '创建身份组';
        // 触发颜色输入事件以更新预览
        document.getElementById('role-color').dispatchEvent(new Event('input'));
    };

    // 打开"创建"模态框
    createRoleBtn.addEventListener('click', () => {
        resetRoleEditorForm();
    });

    // 打开"编辑"模态框
    roleTableBody.addEventListener('click', (event) => {
        const editBtn = event.target.closest('.edit-role-btn');
        if (!editBtn) return;
        
        resetRoleEditorForm();
        const roleId = editBtn.dataset.roleId;
        const roleRow = editBtn.closest('tr');
        const roleName = roleRow.cells[0].textContent.trim();
        const roleColor = roleRow.cells[3].querySelector('code').textContent;

        document.getElementById('role-editor-title').textContent = `编辑身份组: ${roleName}`;
        document.getElementById('edit-role-id').value = roleId;
        document.getElementById('role-name').value = roleName;
        document.getElementById('role-color').value = roleColor;
        document.getElementById('role-color').dispatchEvent(new Event('input'));
        
        // TODO: 在未来，可以添加一个API来获取特定角色的权限和hoist/mentionable状态并填充
        // 目前，编辑时权限将是空的，需要管理员重新勾选。
        
        roleEditorModal.show();
    });

    // 预览颜色
    document.getElementById('role-color').addEventListener('input', (event) => {
        document.getElementById('role-preview').style.backgroundColor = event.target.value;
    });

    // 清除所有权限的复选框
    document.getElementById('clear-all-perms').addEventListener('change', (event) => {
        roleEditorForm.querySelectorAll('input[name="permissions"]').forEach(checkbox => {
            checkbox.checked = !event.target.checked;
        });
    });

    // 提交表单
    roleEditorForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const formData = new FormData(roleEditorForm);
        const saveBtn = document.getElementById('save-role-btn');
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 保存中...';

        try {
            // 【新增】获取 CSRF Token
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

            // 使用 fetch 发送 FormData，并手动添加 Token
            const response = await fetch(`/api/guild/${GUILD_ID}/roles/create_or_edit`, {
                method: 'POST',
                body: formData, // FormData 不需要设置 Content-Type
                headers: {
                    'X-CSRFToken': csrfToken // 【新增】
                }
            });
            const data = await response.json();
            alert(data.message);
            if (response.ok && data.status === 'success') {
                roleEditorModal.hide();
                location.reload();
            }
        } catch (error) {
            console.error('身份组操作失败:', error);
            alert(`发生错误: ${error.message}`);
        } finally {
            saveBtn.disabled = false;
            saveBtn.textContent = '保存更改';
        }
    });
// [ 结束新增代码块 3 ]
}

function initializeSettingsPage() {
    const GUILD_ID = document.body.dataset.guildId;
    if (!GUILD_ID) return;
    const renderers = {
        bot_whitelist: (data) => {
            const list = document.getElementById('bot-whitelist');
            if (!list) return;
            list.innerHTML = !data.whitelist?.length ? '<li class="list-group-item text-muted">白名单是空的。</li>' : data.whitelist.map(bot => `<li class="list-group-item d-flex justify-content-between align-items-center" data-entity-id="${bot.id}">${bot.name} (<code>${bot.id}</code>)<button class="btn btn-danger btn-sm action-btn" data-action="action/bot_whitelist_remove" data-target-id="${bot.id}"><i class="fa-solid fa-trash"></i></button></li>`).join('');
        },
        ai_dep_channels: (data) => {
            const list = document.getElementById('ai-dep-list');
            if (!list) return;
            list.innerHTML = !data.channels?.length ? '<li class="list-group-item text-muted">未设置AI频道。</li>' : data.channels.map(ch => `<li class="list-group-item d-flex justify-content-between align-items-center" data-entity-id="${ch.id}"><span>#${ch.name} (模型: ${ch.model})</span><button class="btn btn-danger btn-sm action-btn" data-action="action/ai_dep_channel_remove" data-target-id="${ch.id}"><i class="fa-solid fa-trash"></i></button></li>`).join('');
        }
    };
    setupCommonEventListeners(GUILD_ID, renderers);
    apiRequest(`/api/guild/${GUILD_ID}/data/bot_whitelist`).then(renderers.bot_whitelist);
    apiRequest(`/api/guild/${GUILD_ID}/data/ai_dep_channels`).then(renderers.ai_dep_channels);
    document.getElementById('deploy-ticket-button')?.addEventListener('click', async () => {
        if (!confirm('这将保存所有设置，并替换掉指定频道中旧的票据按钮（如果有）。确定要继续吗？')) return;
        const form = document.getElementById('ticket-settings-form');
        const formData = new FormData(form);
        let payload = Object.fromEntries(formData.entries());
        payload.staff_role_ids = Array.from(formData.getAll('staff_role_ids'));
        payload.form_id = 'ticket-settings-form-deploy';
        try {
            const data = await apiRequest(`/api/guild/${GUILD_ID}/form_submit`, { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify(payload) 
            });
            alert(data.message);
        } catch (error) {}
    });
}

function initializeChannelControlPage() {
    const pageRoot = document.querySelector('[data-page-id="channel_control"]') || document.body;
    const GUILD_ID = document.body.dataset.guildId || pageRoot.dataset.guildId;
    if (!GUILD_ID) return;
    const ownerId = document.body.dataset.ownerId || pageRoot.dataset.ownerId; 

    console.log("[ChannelControl] Initializing...");

    // ==========================================
    // 1. 初始化 Socket 连接
    // ==========================================
    const socket = io({ transports: ['websocket'], path: '/my-custom-socket-path' });
    
    socket.on('connect', () => {
        console.log("[ChannelControl] Socket connected!");
        socket.emit('join_voice_room', { guild_id: GUILD_ID });
    });

    socket.on('connect_error', (err) => {
        console.error("[ChannelControl] Socket error:", err);
    });

    socket.on('voice_control_error', (data) => {
        alert("语音控制错误: " + (data.message || "未知错误"));
        fetchVoiceStates();
    });

    socket.on('voice_control_status', (data) => {
        console.log("[ChannelControl] Voice status:", data);
    });

    // ==========================================
    // 2. 界面渲染逻辑
    // ==========================================
    const renderVoice = (data) => {
        // --- A. 更新顶部机器人状态栏 ---
        const statusSpan = document.getElementById('bot-voice-status');
        if (statusSpan) {
            if (data.bot_channel_id) {
                const currentCh = data.voice_channels.find(c => c.id === data.bot_channel_id);
                const channelName = currentCh ? escapeHtml(currentCh.name) : '语音频道';
                statusSpan.innerHTML = `<span class="text-success"><i class="fa-solid fa-circle small"></i> 已连接: ${channelName}</span>`;
            } else {
                statusSpan.innerHTML = `<span class="text-muted"><i class="fa-regular fa-circle small"></i> 未连接 (待机中)</span>`;
            }
        }

        // --- B. 渲染语音频道列表 ---
        const grid = document.getElementById('voice-channels-grid');
        if (!grid) return;
        
        if (!data.voice_channels || data.voice_channels.length === 0) {
            grid.innerHTML = '<p class="text-muted p-3">所有语音频道均为空。</p>';
            return;
        }

        grid.innerHTML = data.voice_channels.map(c => 
            `<div class="vc-card">
                <div class="vc-card-header d-flex justify-content-between align-items-center">
                    <span>${escapeHtml(c.name)} <span class="badge bg-secondary" style="font-size: 0.7em;">${c.members.length}</span></span>
                    <!-- 加入按钮 -->
                    <button class="btn btn-sm btn-outline-info btn-bot-join-vc" data-channel-id="${c.id}" style="padding: 1px 8px; font-size: 0.8rem;">
                        <i class="fa-solid fa-right-to-bracket"></i> 加入
                    </button>
                </div>
                <div class="vc-members-list">
                    ${c.members.length === 0 ? '<div class="text-muted small p-2"><i>(空闲)</i></div>' : ''}
                    ${c.members.map(m => {
                        const isOwner = String(m.id) === ownerId;
                        const disabledAttr = isOwner ? 'disabled title="不能操作服务器所有者"' : '';
                        const statusIcon = m.is_deafened ? '<i class="fa-solid fa-ear-deaf text-danger" title="禁听"></i>' : (m.is_muted ? '<i class="fa-solid fa-microphone-slash text-warning" title="禁麦"></i>' : '');
                        const crown = isOwner ? '<i class="fa-solid fa-crown text-warning" title="服主"></i>' : '';
                        const muteBtnText = m.is_muted ? '解麦' : '禁麦';
                        const muteAction = m.is_muted ? 'vc_unmute' : 'vc_mute';
                        let deafenBtn = m.is_deafened 
                            ? `<button class="btn btn-outline-danger action-btn" data-action="action/vc_undeafen" data-target-id="${m.id}" ${disabledAttr}>解听</button>`
                            : `<button class="btn btn-outline-danger action-btn" data-action="action/vc_deafen" data-target-id="${m.id}" ${disabledAttr}>禁听</button>`;

                        return `<div class="vc-member" data-entity-id="${m.id}">
                            <span class="text-truncate" style="max-width: 140px;">
                                <img src="${m.avatar_url}" class="avatar" alt=""> 
                                ${escapeHtml(m.name)} ${crown} ${statusIcon}
                            </span>
                            <div class="btn-group btn-group-sm">
                                <button class="btn btn-outline-warning action-btn" data-action="action/${muteAction}" data-target-id="${m.id}" ${disabledAttr}>${muteBtnText}</button>
                                ${deafenBtn}
                                <button class="btn btn-outline-secondary action-btn" data-action="action/vc_kick" data-target-id="${m.id}" ${disabledAttr}>踢出</button>
                            </div>
                        </div>`;
                    }).join('')}
                </div>
            </div>`
        ).join('');
    };
    
    // ==========================================
    // 3. 数据轮询与事件监听
    // ==========================================
    const fetchVoiceStates = () => apiRequest(`/api/guild/${GUILD_ID}/voice_states`).then(renderVoice).catch(console.error);
    
    // 绑定通用列表按钮 (踢出/禁言等)
    setupCommonEventListeners(GUILD_ID, { voice_states: renderVoice });
    
    // 立即执行一次，然后每5秒轮询
    fetchVoiceStates();
    setInterval(fetchVoiceStates, 5000);

    // 监听 Socket 状态更新，收到后立刻刷新
    socket.on('voice_status_update', (data) => {
        console.log("[Socket] Voice status update received, forcing refresh:", data);
        fetchVoiceStates(); 
    });

    // ==========================================
    // 4. 语音指挥官核心逻辑 (按钮点击事件)
    // ==========================================
    document.body.addEventListener('click', (e) => {
        // --- 处理 "加入" 按钮 ---
        const joinBtn = e.target.closest('.btn-bot-join-vc');
        if (joinBtn) {
            e.preventDefault();
            const channelId = joinBtn.dataset.channelId;
            const channelName = joinBtn.closest('.vc-card-header').querySelector('span').textContent.split(' ')[0];
            console.log(`[点击事件] 加入按钮被点击, 目标频道: ${channelId}`);

            if (socket && socket.connected) {
                // --- 【核心修复】立即更新UI，提供即时反馈 ---
                const statusSpan = document.getElementById('bot-voice-status');
                if (statusSpan) {
                    statusSpan.innerHTML = `<span class="text-info"><i class="fa-solid fa-spinner fa-spin small"></i> 正在连接: ${escapeHtml(channelName)}</span>`;
                }
                // ------------------------------------

                socket.emit('voice_control_join', { guild_id: GUILD_ID, channel_id: channelId });
            } else {
                alert("与服务器的连接断开，请刷新页面重试。");
            }
        }
        
        // --- 处理 "断开" 按钮 ---
        const leaveBtn = e.target.closest('#btn-bot-leave-vc');
        if(leaveBtn) {
            e.preventDefault();
            console.log(`[点击事件] 断开按钮被点击`);
            if (socket && socket.connected) {
                socket.emit('voice_control_leave', { guild_id: GUILD_ID });
            }
        }
    });

    // ==========================================
    // 5. TTS (文字转语音) 逻辑
    // ==========================================
    const ttsBtn = document.getElementById('tts-send-btn');
    const ttsInput = document.getElementById('tts-input');
    
    if (ttsBtn && ttsInput) {
        const sendTTS = () => {
            const text = ttsInput.value.trim();
            if(!text) return;
            
            ttsBtn.disabled = true;
            socket.emit('voice_control_tts', { guild_id: GUILD_ID, text: text });
            
            ttsInput.value = '';
            setTimeout(() => ttsBtn.disabled = false, 1000);
        };
        
        ttsBtn.addEventListener('click', sendTTS);
        ttsInput.addEventListener('keypress', (e) => { 
            if (e.key === 'Enter') sendTTS(); 
        });
    }

    // ==========================================
    // 6. 语音录制与发送逻辑
    // ==========================================
    const recordBtn = document.getElementById('mic-record-btn');
    const previewContainer = document.getElementById('audio-preview-container');
    const audioPlayer = document.getElementById('audio-preview-player');
    const sendBtn = document.getElementById('send-audio-btn');
    
    if(recordBtn && previewContainer && audioPlayer && sendBtn) {
        let mediaRecorder;
        let audioChunks = [];
        let audioBlob = null;
        let isRecording = false;

        recordBtn.addEventListener('click', async () => {
            if (isRecording) {
                // 停止录音
                if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                    mediaRecorder.stop();
                }
            } else {
                // 开始录音
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                    return alert("浏览器不支持麦克风访问或未在 HTTPS 环境下。");
                }
                try {
                    if (window.isSecureContext === false) {
                        alert("麦克风需要 HTTPS 或 localhost 安全环境。请使用 https:// 域名访问面板。");
                        return;
                    }
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    mediaRecorder = new MediaRecorder(stream);
                    audioChunks = [];
                    
                    mediaRecorder.ondataavailable = event => audioChunks.push(event.data);
                    
                    mediaRecorder.onstop = () => {
                        audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                        const audioUrl = URL.createObjectURL(audioBlob);
                        audioPlayer.src = audioUrl;
                        
                        // 显示预览，隐藏录音按钮
                        previewContainer.classList.remove('d-none');
                        recordBtn.classList.add('d-none');
                        
                        // 释放麦克风流
                        stream.getTracks().forEach(track => track.stop());
                    };

                    mediaRecorder.start();
                    isRecording = true;

                    // 改变按钮样式为"停止"
                    recordBtn.classList.remove('btn-outline-light');
                    recordBtn.classList.add('btn-danger');
                    recordBtn.innerHTML = '<i class="fa-solid fa-stop"></i> 停止录音';
                } catch (err) {
                    console.error("Microphone access error:", err);
                    const message = err.name === 'NotAllowedError'
                        ? "浏览器拒绝了麦克风权限。请点击地址栏左侧的网站权限图标，允许麦克风后刷新页面。"
                        : `无法启动麦克风: ${err.message}`;
                    alert(message);
                }
            }
        });
        
        // 发送录音
        sendBtn.addEventListener('click', () => {
            if (audioBlob) {
                socket.emit('voice_control_blob', { guild_id: parseInt(GUILD_ID), audio_blob: audioBlob });
                
                // 重置界面
                previewContainer.classList.add('d-none');
                recordBtn.classList.remove('d-none');
                recordBtn.classList.remove('btn-danger');
                recordBtn.classList.add('btn-outline-light');
                recordBtn.innerHTML = '<i class="fa-solid fa-microphone"></i> 开始录音';
                
                isRecording = false;
                audioBlob = null;
            }
        });
    }
}

function initializeModerationPage() {
    const GUILD_ID = document.body.dataset.guildId;
    if (!GUILD_ID) return;
    const renderers = {
        muted_users: (data) => {
            const tbody = document.getElementById('muted-users-list'); if (!tbody) return;
            if (!data.muted_users || data.muted_users.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">当前没有活动的禁言记录。</td></tr>';
                return;
            }
            tbody.innerHTML = data.muted_users.map(mute => `<tr data-entity-id="${mute.user.id}"><td><img src="${mute.user.avatar_url}" class="avatar" alt=""> ${mute.user.name}</td><td>${mute.reason || 'N/A'}</td><td id="countdown-${mute.user.id}" class="countdown-timer" data-expires="${mute.expires_at}">计算中...</td><td><button class="btn btn-sm btn-outline-success action-btn" data-action="action/unmute" data-target-id="${mute.user.id}">解除禁言</button></td></tr>`).join('');
            startAllCountdowns();
        }
    };
    setupCommonEventListeners(GUILD_ID, renderers);
    apiRequest(`/api/guild/${GUILD_ID}/muted_users`).then(renderers.muted_users);
}

function initializeAnnouncementsPage() {
    const GUILD_ID = document.body.dataset.guildId;
    if (!GUILD_ID) return;
    setupCommonEventListeners(GUILD_ID);
}

function initializeAuditCorePage() {
    const GUILD_ID = document.body.dataset.guildId;
    if (!GUILD_ID) return;
    
    const logContainer = document.getElementById('audit-log-container');
    const exemptUserForm = document.getElementById('exempt-user-form');
    const exemptChannelForm = document.getElementById('exempt-channel-form');
    const exemptUsersList = document.getElementById('exempt-users-list');
    const exemptChannelsList = document.getElementById('exempt-channels-list');
    
    function renderExemptUsers(users) {
        if (!exemptUsersList) return;
        exemptUsersList.innerHTML = !users?.length ? '<li class="list-group-item text-muted">无豁免用户</li>' : users.map(u => `
            <li class="list-group-item d-flex justify-content-between align-items-center" data-entity-id="${u.id}">
                <span>${u.name}</span>
                <button class="btn btn-sm btn-outline-danger action-btn" data-action="action/ai_exempt_remove_user" data-target-id="${u.id}"><i class="fa-solid fa-trash"></i></button>
            </li>`).join('');
    }

    function renderExemptChannels(channels) {
        if (!exemptChannelsList) return;
        exemptChannelsList.innerHTML = !channels?.length ? '<li class="list-group-item text-muted">无豁免频道</li>' : channels.map(c => `
            <li class="list-group-item d-flex justify-content-between align-items-center" data-entity-id="${c.id}">
                <span>#${c.name}</span>
                <button class="btn btn-sm btn-outline-danger action-btn" data-action="action/ai_exempt_remove_channel" data-target-id="${c.id}"><i class="fa-solid fa-trash"></i></button>
            </li>`).join('');
    }
    
    async function handleExemptFormSubmit(event) {
        event.preventDefault();
        const form = event.target;
        const formData = new FormData(form);
        const payload = Object.fromEntries(formData.entries());
        payload.form_id = form.id;
        try {
            const data = await apiRequest(`/api/guild/${GUILD_ID}/form_submit`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            alert(data.message);
            if (data.status === 'success') {
                form.reset();
                fetchExemptions(); 
            }
        } catch (error) {}
    }

    if (exemptUserForm) exemptUserForm.addEventListener('submit', handleExemptFormSubmit);
    if (exemptChannelForm) exemptChannelForm.addEventListener('submit', handleExemptFormSubmit);

    async function fetchExemptions() {
        try {
            const [userData, channelData] = await Promise.all([
                apiRequest(`/api/guild/${GUILD_ID}/data/exempt_users`),
                apiRequest(`/api/guild/${GUILD_ID}/data/exempt_channels`)
            ]);
            if (userData.users) renderExemptUsers(userData.users);
            if (channelData.channels) renderExemptChannels(channelData.channels);
        } catch (error) { console.error("加载豁免列表失败:", error); }
    }
    
    document.body.addEventListener('click', async (event) => {
        const button = event.target.closest('.action-btn');
        if (!button) return;
        const action = button.dataset.action;
        if (action === 'action/ai_exempt_remove_user' || action === 'action/ai_exempt_remove_channel') {
            event.preventDefault();
            const targetId = button.dataset.targetId;
            if (!confirm(`确定要移除ID为 ${targetId} 的豁免项吗？`)) return;
            try {
                const response = await apiRequest(`/api/guild/${GUILD_ID}/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target_id: targetId }) });
                alert(response.message);
                if (response.status === 'success') fetchExemptions();
            } catch (error) {}
        }
    });

    function renderViolationCard(data) {
        if (!logContainer || document.querySelector(`.violation-card[data-event-id="${data.event_id}"]`)) return;
        const placeholder = document.getElementById('no-logs-placeholder');
        if (placeholder) placeholder.style.display = 'none';
        const actionButtonsHtml = data.auto_deleted ? `<div class="ms-auto d-flex align-items-center gap-2"><span class="text-danger small"><i class="fa-solid fa-trash-can"></i> 已自动删除</span><button class="btn btn-sm btn-danger action-btn" data-action="audit_warn">仅警告用户</button></div>` : `<div class="ms-auto btn-group"><button class="btn btn-sm btn-outline-secondary action-btn" data-action="audit_ignore">忽略</button><button class="btn btn-sm btn-outline-danger action-btn" data-action="audit_delete">删除消息</button><button class="btn btn-sm btn-danger action-btn" data-action="audit_warn_and_delete">警告并删除</button></div>`;
        const cardHtml = `<div class="card bg-dark-2 mb-3 violation-card" data-event-id="${data.event_id}" data-message-id="${data.message.id}" data-channel-id="${data.message.channel_id}" data-user-id="${data.user.id}"><div class="card-body"><div class="d-flex align-items-center mb-2"><img src="${data.user.avatar_url}" class="avatar me-3"><div><strong>${data.user.name}</strong><small class="text-muted d-block">ID: <a href="${data.message.jump_url}" target="_blank" rel="noopener noreferrer">${data.user.id}</a></small></div></div><p class="text-warning small mb-1">违规类型: ${data.violation_type}</p><p class="text-muted small">在 #${data.message.channel_name} | ${new Date(data.timestamp).toLocaleString()}</p><p class="message-content p-2 bg-black bg-opacity-25 rounded">${data.message.content}</p><hr class="my-2"><div class="d-flex align-items-center">${actionButtonsHtml}</div></div></div>`;
        logContainer.insertAdjacentHTML('afterbegin', cardHtml);
    }
    async function fetchHistory() {
        try {
            const historyData = await apiRequest(`/api/guild/${GUILD_ID}/audit_history`);
            if (historyData.status === 'success' && historyData.events.length > 0) {
                logContainer.innerHTML = ''; 
                historyData.events.forEach(event => renderViolationCard(event));
            } else if (historyData.events.length === 0) {
                const placeholder = document.getElementById('no-logs-placeholder');
                if (placeholder) placeholder.style.display = 'block';
            }
        } catch (error) { console.error("获取审核历史失败:", error); }
    }
    try {
        console.log("[AuditCorePage] 正在初始化Socket.IO连接 (强制WebSocket, 自定义路径)...");
        const socket = io({ transports: ['websocket'], path: '/my-custom-socket-path' });
        socket.on('connect', () => {
            console.log(`%c[AuditCorePage] Socket.IO已连接! Socket ID: ${socket.id}`, 'color: #00ff00; font-weight: bold;');
            socket.emit('join_audit_room', { guild_id: GUILD_ID });
        });
        socket.on('new_violation', (data) => renderViolationCard(data));
        socket.on('connect_error', (err) => console.error('[AuditCorePage] Socket.IO连接错误:', err));
    } catch (e) { console.error("无法初始化Socket.IO:", e); }
    logContainer.addEventListener('click', (event) => {
        const button = event.target.closest('.action-btn');
        if (!button) return;
        event.preventDefault();
        const card = button.closest('.violation-card');
        if (!card) return;
        const payload = { action: button.dataset.action, event_id: card.dataset.eventId, message_id: card.dataset.messageId, channel_id: card.dataset.channelId, target_user_id: card.dataset.userId };
        apiRequest(`/api/guild/${GUILD_ID}/audit_action`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
        .then(response => {
            if (response.status === 'success') {
                card.style.opacity = '0.5'; card.style.borderColor = 'gray';
                const buttonContainer = card.querySelector('.d-flex.align-items-center:last-child');
                if (buttonContainer) buttonContainer.innerHTML = `<p class="text-success m-0 ms-auto"><i class="fa-solid fa-check"></i> 已处理: ${payload.action.replace('audit_', '')}</p>`;
            } else { alert(`操作失败: ${response.message}`); }
        }).catch(err => console.error("审核操作失败:", err));
    });
    fetchHistory();
    fetchExemptions();
}

function initializeWarningsPage() {
    const GUILD_ID = document.body.dataset.guildId;
    if (!GUILD_ID) return;
    const warnBtn = document.getElementById('issue-warn-btn');
    const unwarnBtn = document.getElementById('revoke-warn-btn');
    const form = document.getElementById('warnings-form');
    const userSelect = form.querySelector('select[name="user_id"]');
    const reasonInput = form.querySelector('input[name="reason"]');
    const warnedUsersList = document.getElementById('warned-users-list');
    const renderWarnedUsers = (data) => {
        if (!warnedUsersList) return;
        if (!data.warned_users || data.warned_users.length === 0) {
            warnedUsersList.innerHTML = '<li class="list-group-item text-muted text-center">系统扫描完成：无警告记录。</li>'; return;
        }
        warnedUsersList.innerHTML = data.warned_users.map(user => `<li class="list-group-item d-flex justify-content-between align-items-center"><span><img src="${user.avatar_url}" class="avatar" alt="">${user.name}</span><span class="warn-count-tag warn-count-${Math.min(user.warn_count, 3)}">${user.warn_count} / 3</span></li>`).join('');
    };
    const fetchWarnedUsers = () => apiRequest(`/api/guild/${GUILD_ID}/warnings`).then(renderWarnedUsers).catch(err => console.error("无法获取警告列表:", err));
    const handleWarnAction = async (action) => {
        const userId = userSelect.value;
        const reason = reasonInput.value || "无指定原因";
        if (!userId) { alert("请选择一个目标用户！"); return; }
        const actionText = action === 'warn' ? '发出警告' : '撤销警告';
        if (!confirm(`确定要对用户 ${userSelect.options[userSelect.selectedIndex].text} ${actionText}吗？`)) return;
        try {
            const response = await apiRequest(`/api/guild/${GUILD_ID}/action/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target_id: userId, reason: reason }) });
            alert(response.message);
            if (response.status === 'success') { fetchWarnedUsers(); form.reset(); }
        } catch (error) {}
    };
    warnBtn.addEventListener('click', () => handleWarnAction('warn'));
    unwarnBtn.addEventListener('click', () => handleWarnAction('unwarn'));
    fetchWarnedUsers();
}

function initializePermissionsPage() {
    const GUILD_ID = document.body.dataset.guildId;
    if (!GUILD_ID) return;
    const form = document.getElementById('permission-group-form');
    const roleSelect = document.getElementById('role-select');
    const allCheckboxes = form.querySelectorAll('input[name="permissions"]');
    const editingRoleIdInput = document.getElementById('editing_role_id');
    const saveBtn = document.getElementById('save-perm-btn');
    const cancelBtn = document.getElementById('cancel-edit-btn');
    const groupsList = document.getElementById('permission-groups-list');
    const PAGE_NAMES = {};
    document.querySelectorAll('.form-check-label').forEach(label => {
        const input = document.getElementById(label.getAttribute('for'));
        if (input) PAGE_NAMES[input.value] = label.textContent.trim();
    });
    function renderPermissionGroups(permissions) {
        if (!groupsList) return;
        groupsList.innerHTML = '';
        if (Object.keys(permissions).length === 0) { groupsList.innerHTML = '<p class="text-muted text-center p-3">还没有创建任何权限组。</p>'; return; }
        for (const [roleId, data] of Object.entries(permissions)) {
            const permsHtml = data.permissions.map(p => {
                const permData = PAGE_NAMES[p] || p;
                let badgeClass = p.startsWith('page_') ? 'bg-primary' : 'bg-info';
                return `<span class="badge ${badgeClass} me-1">${permData}</span>`;
            }).join(' ');
            const groupHtml = `<div class="list-group-item" data-role-id="${roleId}"><div class="d-flex w-100 justify-content-between"><h5 class="mb-1">@${data.name}</h5><div><button class="btn btn-sm btn-outline-info edit-perm-btn">编辑</button><button class="btn btn-sm btn-outline-danger delete-perm-btn">删除</button></div></div><p class="mb-1">${permsHtml || '<span class="text-muted">无任何页面权限</span>'}</p></div>`;
            groupsList.insertAdjacentHTML('beforeend', groupHtml);
        }
    }
    function resetForm() { form.reset(); editingRoleIdInput.value = ''; roleSelect.disabled = false; saveBtn.textContent = '保存权限组'; cancelBtn.style.display = 'none'; allCheckboxes.forEach(cb => { cb.checked = false; cb.indeterminate = false; }); }
    async function fetchPermissions() { try { const data = await apiRequest(`/api/guild/${GUILD_ID}/permissions`); if (data.status === 'success') renderPermissionGroups(data.permissions); } catch (error) {} }
    form.addEventListener('change', (event) => {
        const target = event.target;
        if (target.classList.contains('parent-permission')) {
            form.querySelectorAll(`[data-parent="${target.id}"]`).forEach(cb => { cb.checked = target.checked; cb.indeterminate = false; });
        } else if (target.classList.contains('child-permission')) {
            const parentCheckbox = document.getElementById(target.dataset.parent);
            if (!parentCheckbox) return;
            const childCheckboxes = form.querySelectorAll(`[data-parent="${parentCheckbox.id}"]`);
            const allChecked = Array.from(childCheckboxes).every(cb => cb.checked);
            const someChecked = Array.from(childCheckboxes).some(cb => cb.checked);
            parentCheckbox.checked = allChecked;
            parentCheckbox.indeterminate = !allChecked && someChecked;
        }
    });
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const selectedPermissions = Array.from(allCheckboxes).filter(cb => cb.checked || cb.indeterminate).map(cb => cb.value);
        const roleId = editingRoleIdInput.value || roleSelect.value;
        if (!roleId) { alert('请选择一个身份组！'); return; }
        try {
            const data = await apiRequest(`/api/guild/${GUILD_ID}/permissions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'save', role_id: roleId, permissions: selectedPermissions }) });
            if (data.status === 'success') { alert(data.message); renderPermissionGroups(data.permissions); resetForm(); } else { alert(`保存失败: ${data.message}`); }
        } catch(e) {}
    });
    groupsList.addEventListener('click', async (event) => {
        const target = event.target;
        const groupItem = target.closest('.list-group-item');
        if (!groupItem) return;
        const roleId = groupItem.dataset.roleId;
        if (target.classList.contains('edit-perm-btn')) {
            resetForm(); roleSelect.value = roleId; roleSelect.disabled = true; editingRoleIdInput.value = roleId;
            const data = (await apiRequest(`/api/guild/${GUILD_ID}/permissions`)).permissions;
            const groupPerms = data[roleId].permissions;
            allCheckboxes.forEach(cb => { cb.checked = groupPerms.includes(cb.value); });
            document.querySelectorAll('.parent-permission').forEach(parentCb => {
                const childCheckboxes = form.querySelectorAll(`[data-parent="${parentCb.id}"]`);
                if (childCheckboxes.length > 0) {
                     const allChecked = Array.from(childCheckboxes).every(cb => cb.checked);
                     const someChecked = Array.from(childCheckboxes).some(cb => cb.checked);
                     parentCb.checked = allChecked;
                     parentCb.indeterminate = !allChecked && someChecked;
                }
            });
            saveBtn.textContent = '更新权限组'; cancelBtn.style.display = 'block'; window.scrollTo({ top: 0, behavior: 'smooth' });
        }
        if (target.classList.contains('delete-perm-btn')) {
            if (!confirm(`确定要删除这个权限组吗？`)) return;
            try {
                 const data = await apiRequest(`/api/guild/${GUILD_ID}/permissions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'delete', role_id: roleId }) });
                 if (data.status === 'success') { alert(data.message); renderPermissionGroups(data.permissions); } else { alert(`删除失败: ${data.message}`); }
            } catch(e) {}
        }
    });
    cancelBtn.addEventListener('click', resetForm);
    fetchPermissions();
}

function initializeSuperuserAccountsPage() {
    console.log("初始化副账号管理页面...");
    const form = document.getElementById('sub-account-form');
    const accountIdInput = document.getElementById('account_id');
    const accountNameInput = document.getElementById('account_name');
    const allGuildsSwitch = document.getElementById('can_manage_all_guilds');
    const guildSelectContainer = document.getElementById('guild-select-container');
    const guildsSelect = document.getElementById('guilds');
    const globalPermsCheckboxes = document.querySelectorAll('input[name="global_permissions"]');
    const accountsListContainer = document.getElementById('sub-accounts-list');
    const saveBtn = document.getElementById('save-account-btn');
    const cancelBtn = document.getElementById('cancel-edit-btn');
    const formTitle = document.getElementById('form-title');
    const newKeyModal = new bootstrap.Modal(document.getElementById('newKeyModal'));
    const newKeyDisplay = document.getElementById('new-access-key-display');
    const copyKeyBtn = document.getElementById('copy-key-btn');
    const renderSubAccounts = (accounts) => {
        accountsListContainer.innerHTML = '';
        if (!accounts || accounts.length === 0) { accountsListContainer.innerHTML = '<p class="text-center text-muted p-3">没有已创建的副账号。</p>'; return; }
        accounts.forEach(acc => {
            const lastUsed = acc.last_used_at ? new Date(acc.last_used_at * 1000).toLocaleString() : '从未使用';
            const perms = acc.permissions;
            let permsDesc = perms.can_manage_all_guilds ? '<span class="badge bg-success">可管理所有服务器</span>' : (perms.guilds && perms.guilds.length > 0 ? `<span class="badge bg-info">${perms.guilds.length} 个特定服务器</span>` : '<span class="badge bg-secondary">无服务器权限</span>');
            const accountElement = document.createElement('div');
            accountElement.className = 'list-group-item';
            accountElement.dataset.accountId = acc.id;
            accountElement.dataset.accountData = JSON.stringify(acc);
            accountElement.innerHTML = `<div class="d-flex w-100 justify-content-between"><h5 class="mb-1">${acc.account_name}</h5><div><button class="btn btn-sm btn-outline-info edit-account-btn">编辑</button><button class="btn btn-sm btn-outline-danger delete-account-btn">删除</button></div></div><p class="mb-1"><strong>权限:</strong> ${permsDesc}</p><small class="text-muted">创建于: ${new Date(acc.created_at * 1000).toLocaleString()} | 最后使用: ${lastUsed}</small>`;
            accountsListContainer.appendChild(accountElement);
        });
    };
    const fetchAccounts = async () => { try { const data = await apiRequest('/api/superuser/accounts'); if (data.status === 'success') renderSubAccounts(data.accounts); } catch (e) { accountsListContainer.innerHTML = '<p class="text-center text-danger p-3">加载账号列表失败。</p>'; } };
    const resetForm = () => { form.reset(); accountIdInput.value = ''; saveBtn.textContent = '创建并生成密钥'; formTitle.textContent = '创建新副账号'; cancelBtn.style.display = 'none'; guildSelectContainer.style.display = 'block'; allGuildsSwitch.checked = false; };
    allGuildsSwitch.addEventListener('change', () => { guildSelectContainer.style.display = allGuildsSwitch.checked ? 'none' : 'block'; });
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const accountId = accountIdInput.value;
        const action = accountId ? 'update' : 'create';
        const selectedGuilds = Array.from(guildsSelect.selectedOptions).map(opt => opt.value);
        const selectedGlobalPerms = Array.from(globalPermsCheckboxes).filter(cb => cb.checked).map(cb => cb.value);
        const payload = { action, account_id: accountId, account_name: accountNameInput.value, permissions: { can_manage_all_guilds: allGuildsSwitch.checked, guilds: selectedGuilds, global_permissions: selectedGlobalPerms, guild_specific_permissions: {} } };
        try {
            const data = await apiRequest('/api/superuser/accounts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            alert(data.message);
            if (data.status === 'success') {
                if (action === 'create' && data.access_key) { newKeyDisplay.textContent = data.access_key; newKeyModal.show(); }
                resetForm(); fetchAccounts();
            }
        } catch (e) {}
    });
    accountsListContainer.addEventListener('click', async (event) => {
        const target = event.target;
        const accountItem = target.closest('.list-group-item');
        if (!accountItem) return;
        const accountId = accountItem.dataset.accountId;
        if (target.classList.contains('edit-account-btn')) {
            const accountData = JSON.parse(accountItem.dataset.accountData);
            resetForm(); formTitle.textContent = `编辑账号: ${accountData.account_name}`;
            saveBtn.textContent = '更新账号权限'; cancelBtn.style.display = 'block';
            accountIdInput.value = accountData.id; accountNameInput.value = accountData.account_name;
            allGuildsSwitch.checked = accountData.permissions.can_manage_all_guilds;
            allGuildsSwitch.dispatchEvent(new Event('change'));
            Array.from(guildsSelect.options).forEach(opt => { opt.selected = accountData.permissions.guilds.includes(opt.value); });
            globalPermsCheckboxes.forEach(cb => { cb.checked = accountData.permissions.global_permissions.includes(cb.value); });
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
        if (target.classList.contains('delete-perm-btn')) {
            if (!confirm(`确定要删除账号 "${accountItem.querySelector('h5').textContent}" 吗？`)) return;
            try {
                const data = await apiRequest('/api/superuser/accounts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'delete', account_id: accountId }) });
                alert(data.message); if (data.status === 'success') fetchAccounts();
            } catch (e) {}
        }
    });
    cancelBtn.addEventListener('click', resetForm);
    copyKeyBtn.addEventListener('click', () => { navigator.clipboard.writeText(newKeyDisplay.textContent).then(() => { copyKeyBtn.textContent = '已复制!'; setTimeout(() => { copyKeyBtn.innerHTML = '<i class="fa-solid fa-copy"></i> 复制到剪贴板'; }, 2000); }); });
    fetchAccounts();
}

function initializeBotProfilePage() {
    console.log("初始化机器人简介页面。此页面目前是纯表单提交，不需要额外的JS初始化。");
}

async function handleAction(button, GUILD_ID, renderers = {}, noConfirm = false) {
    const action = button.dataset.action;
    let targetId = button.dataset.targetId || button.closest('[data-entity-id]')?.dataset.entityId;
    if (!action || !targetId) { alert("错误: 操作或目标ID缺失。"); return; }
    if (action === "data/kb") targetId = parseInt(targetId, 10);
    const subAction = button.dataset.subAction;
    let confirmationMessage = `您确定要对ID为 ${targetId} 的项目执行此操作吗？`;
    const actionTexts = { 'action/unmute': `解除用户 ${targetId} 的禁言`, 'action/kick': `踢出用户 ${targetId}`, 'action/ban': `封禁用户 ${targetId}`, 'action/delete_role': `删除身份组 ${targetId}` };
    if (actionTexts[action]) confirmationMessage = `您确定要${actionTexts[action]}吗？`;
    if (!noConfirm && !confirm(confirmationMessage)) return;
    const payload = { target_id: targetId, reason: '从Web面板操作' };
    if (subAction) {
        payload.action = subAction;
        if (action === 'shop/action' && subAction === 'delete') payload.item_slug = targetId;
        if (action === 'data/kb') payload.index = targetId;
        if (action === 'data/faq') payload.keyword = targetId;
    }
    try {
        const data = await apiRequest(`/api/guild/${GUILD_ID}/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        alert(data.message);
        if (data.status === "success") {
            const itemElement = button.closest('[data-entity-id]');
            if (itemElement) {
                itemElement.style.transition = 'opacity 0.5s ease'; itemElement.style.opacity = '0';
                setTimeout(() => {
                    const parentContainer = itemElement.parentElement;
                    itemElement.remove();
                    if (parentContainer && parentContainer.childElementCount === 0) {
                        const rendererKey = Object.keys(renderers).find(key => parentContainer.id.includes(key));
                        if(rendererKey && renderers[rendererKey]) {
                            const emptyData = {};
                            const key = rendererKey.replace(/-/g, '_');
                            renderers[rendererKey]({ [key]: [] });
                        }
                    }
                }, 500);
            }
        }
    } catch (error) {}
}

function startAllCountdowns() {
    if (window.countdownInterval) clearInterval(window.countdownInterval);
    const countdownElements = document.querySelectorAll('.countdown-timer');
    if (countdownElements.length === 0) return;
    const updateTimers = () => {
        countdownElements.forEach(el => {
            const expires = parseInt(el.dataset.expires, 10);
            if (isNaN(expires) || !expires) { el.textContent = "永久"; return; }
            const now = Math.floor(Date.now() / 1000);
            const remaining = expires - now;
            if (remaining <= 0) {
                el.textContent = "已到期";
                el.classList.remove('countdown-timer');
                el.classList.add('text-success');
                const row = el.closest('tr');
                if(row) setTimeout(() => { row.style.transition = 'opacity 0.5s ease'; row.style.opacity = '0'; setTimeout(() => row.remove(), 500); }, 1000);
            } else {
                const days = Math.floor(remaining / 86400);
                const hours = Math.floor((remaining % 86400) / 3600);
                const minutes = Math.floor((remaining % 3600) / 60);
                const seconds = remaining % 60;
                let timeString = '';
                if (days > 0) timeString += `${days}天 `;
                if (hours > 0 || days > 0) timeString += `${hours.toString().padStart(2, '0')}:`;
                timeString += `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
                el.textContent = timeString;
            }
        });
    };
    updateTimers();
    window.countdownInterval = setInterval(updateTimers, 1000);
}
function initializeBackupPage() {
    const GUILD_ID = document.body.dataset.guildId;
    if (!GUILD_ID) {
        console.error("Backup Page Error: Missing guild-id in body dataset.");
        return;
    }

    // 获取所有需要的DOM元素
    const createBtn = document.getElementById('create-backup-btn');
    const restoreForm = document.getElementById('restore-form');
    const fileInput = document.getElementById('backup-file-input');
    const confirmInput = document.getElementById('confirmation-phrase');
    const restoreBtn = document.getElementById('restore-btn');
    const logCard = document.getElementById('restore-log-card');
    const logContainer = document.getElementById('restore-log-container');
    let socket; // 用于Socket.IO连接

    // 1. 备份按钮的事件监听器
    createBtn.addEventListener('click', async () => {
        createBtn.disabled = true;
        createBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 正在生成...';
        try {
            // 向后端API请求备份文件
            const response = await fetch(`/api/guild/${GUILD_ID}/backup`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.message || '备份失败，服务器返回错误。');
            }
            // 将响应体转换为Blob对象
            const blob = await response.blob();
            // 创建一个临时的下载链接
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = downloadUrl;

            // 从响应头中智能地获取文件名
            const disposition = response.headers.get('Content-Disposition');
            let filename = `backup-${GUILD_ID}.json`; // 默认文件名
            if (disposition && disposition.indexOf('attachment') !== -1) {
                const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
                const matches = filenameRegex.exec(disposition);
                if (matches != null && matches[1]) {
                    filename = matches[1].replace(/['"]/g, '');
                }
            }
            a.download = filename;

            // 触发下载并清理
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(downloadUrl);
            a.remove();
        } catch (error) {
            alert(`创建备份时出错: ${error.message}`);
        } finally {
            // 恢复按钮状态
            createBtn.disabled = false;
            createBtn.innerHTML = '<i class="fas fa-download"></i> 创建并下载备份';
        }
    });

    // 2. 恢复表单的提交事件监听器
    restoreForm.addEventListener('submit', (event) => {
        event.preventDefault(); // 阻止表单的默认提交行为
        const file = fileInput.files[0];
        if (!file) {
            alert('请选择一个备份文件。');
            return;
        }

        // 严格检查确认短语
        const expectedPhraseElement = document.querySelector('#restore-form code');
        if (!expectedPhraseElement) {
            alert('错误：无法在页面上找到确认短语元素。');
            return;
        }
        const expectedPhrase = expectedPhraseElement.textContent;
        if (confirmInput.value.trim() !== expectedPhrase.trim()) {
            alert('确认短语不匹配！请仔细输入。');
            return;
        }
        
        // 最终警告
        if (!confirm("最后警告：这将删除服务器所有频道和角色并从文件恢复。此操作不可逆！您确定吗？")) return;

        // 使用FileReader来读取文件内容
        const reader = new FileReader();
        reader.onload = (e) => {
            // 【核心】不在这里解析JSON，直接获取文件的文本内容
            const backupDataAsString = e.target.result; 

            // 更新UI，显示正在处理
            restoreBtn.disabled = true;
            restoreBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 正在连接服务器...';
            logCard.style.display = 'block';
            logContainer.innerHTML = '';
            
            // 调用函数，启动Socket连接并发送恢复请求
            startRestoreProcess(backupDataAsString);
        };
        // 【核心】将文件作为纯文本字符串读取
        reader.readAsText(file);
    });

    // 3. 启动Socket.IO连接并发送恢复请求的函数
    function startRestoreProcess(backupDataString) {
        // 如果已有连接，先断开，确保是全新的会话
        if (socket) socket.disconnect();
        
        // 初始化Socket.IO连接
        socket = io({ transports: ['websocket'], path: '/my-custom-socket-path' });

        // A. 连接成功时的回调
        socket.on('connect', () => {
            logContainer.innerHTML += `<span class="restore-log-entry log-success">[${new Date().toLocaleTimeString()}] 已连接到日志服务器...</span>`;
            restoreBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 正在启动恢复...';
            
            // 【核心】发送包含文件字符串的事件给后端
            socket.emit('start_restore', {
                guild_id: GUILD_ID,
                backup_data_str: backupDataString, // 使用新字段名发送字符串
                confirmation: confirmInput.value
            });
        });

        // B. 接收到后端发来的进度更新时的回调
        socket.on('restore_progress', (data) => {
            const logEntry = document.createElement('span');
            logEntry.className = `restore-log-entry log-${data.type}`; // 根据类型设置颜色
            logEntry.textContent = `[${new Date().toLocaleTimeString()}] ${data.message}`;
            logContainer.appendChild(logEntry);
            logContainer.scrollTop = logContainer.scrollHeight; // 自动滚动到最新日志
        });

        // C. 接收到恢复完成或失败的信号时的回调
        socket.on('restore_finished', (data) => {
             restoreBtn.disabled = false;
             restoreBtn.innerHTML = '<i class="fas fa-undo"></i> 我已了解风险，开始恢复';
             if (socket) {
                 socket.disconnect(); // 任务完成，断开连接
                 socket = null;
             }
        });

        // D. 连接出错时的回调
        socket.on('connect_error', (err) => {
            logContainer.innerHTML += `<span class="restore-log-entry log-error">无法连接到日志服务器: ${err.message}</span>`;
            restoreBtn.disabled = false;
            restoreBtn.innerHTML = '<i class="fas fa-undo"></i> 我已了解风险，开始恢复';
        });
    }
}
function initializeSuperuserBroadcastPage() {
    console.log("初始化全局广播页面...");
    const form = document.getElementById('broadcast-form');
    // 【修改】获取新的HTML元素
    const allGuildsSwitch = document.getElementById('broadcast-all-switch');
    const targetGuildsSelect = document.getElementById('target-guilds-select');
    
    const guildSelect = document.getElementById('invite-guild-select');
    const generateBtn = document.getElementById('generate-invite-btn');
    const linkDisplay = document.getElementById('invite-link-display');
    const startBtn = document.getElementById('start-broadcast-btn');
    const logCard = document.getElementById('log-card');
    const logContainer = document.getElementById('broadcast-log');
    const totalUsersSpan = document.getElementById('total-users-count');
    let socket;

    apiRequest('/api/stats').then(data => {
        if (data && data.users) {
            totalUsersSpan.textContent = data.users.toLocaleString();
        }
    });

    guildSelect.addEventListener('change', () => {
        generateBtn.disabled = !guildSelect.value;
    });

    // 【新增】为 "广播到所有服务器" 开关添加事件监听
    allGuildsSwitch.addEventListener('change', () => {
        // 如果开关打开，则禁用并清空多选框；否则启用它。
        targetGuildsSelect.disabled = allGuildsSwitch.checked;
        if (allGuildsSwitch.checked) {
            Array.from(targetGuildsSelect.options).forEach(opt => opt.selected = false);
        }
    });

    generateBtn.addEventListener('click', async () => {
        const guildId = guildSelect.value;
        if (!guildId) return;
        generateBtn.disabled = true;
        generateBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
        try {
            const data = await apiRequest(`/api/guild/${guildId}/generate_invite`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });
            if (data.status === 'success' && data.invite_url) {
                linkDisplay.value = data.invite_url;
            } else {
                alert(`生成邀请链接失败: ${data.message}`);
                linkDisplay.value = '';
            }
        } catch (e) {
            alert(`生成邀请链接时出错: ${e.message}`);
        } finally {
            generateBtn.disabled = false;
            generateBtn.innerHTML = '生成/更新链接';
        }
    });

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        if (document.getElementById('confirmation-input').value !== 'START GLOBAL BROADCAST') {
            alert('确认短语不正确！');
            return;
        }

        // 【新增】检查目标服务器选择
        const broadcastToAll = allGuildsSwitch.checked;
        const selectedGuilds = Array.from(targetGuildsSelect.selectedOptions).map(opt => opt.value);

        if (!broadcastToAll && selectedGuilds.length === 0) {
            alert('请选择至少一个目标服务器，或勾选“广播到所有服务器”。');
            return;
        }
        
        const targetDesc = broadcastToAll ? "所有服务器" : `${selectedGuilds.length}个选定服务器`;
        if (!confirm(`最后警告：您即将向 ${targetDesc} 的所有用户发送私信。确定要继续吗？`)) {
            return;
        }

        startBtn.disabled = true;
        startBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 广播正在进行...';
        logCard.style.display = 'block';
        logContainer.innerHTML = '';
        
        const formData = new FormData(form);
        const payload = {
            title: formData.get('title'),
            message: formData.get('message'),
            invite_url: linkDisplay.value,
            // 【新增】将选择的目标服务器信息加入payload
            broadcast_to_all: broadcastToAll,
            target_guilds: selectedGuilds
        };

        if (socket) socket.disconnect();
        socket = io({ transports: ['websocket'], path: '/my-custom-socket-path' });

        socket.on('connect', () => {
            logContainer.innerHTML += `<span class="log-entry log-success">[${new Date().toLocaleTimeString()}] 已连接到广播服务器...</span>`;
            socket.emit('start_global_broadcast', payload);
        });

        socket.on('broadcast_log', (data) => {
            const logEntry = document.createElement('span');
            logEntry.className = `log-entry log-${data.type || 'info'}`;
            logEntry.textContent = `[${new Date().toLocaleTimeString()}] ${data.message}`;
            logContainer.appendChild(logEntry);
            logContainer.scrollTop = logContainer.scrollHeight;
        });
        
        socket.on('broadcast_finished', (data) => {
            startBtn.disabled = false;
            startBtn.innerHTML = '<i class="fas fa-broadcast-tower"></i> 启动广播';
            const finalMessage = data.status === 'success' ? '广播任务完成！' : '广播任务因错误而终止。';
            logContainer.innerHTML += `<span class="log-entry log-${data.status}">${finalMessage}</span>`;
            if (socket) {
                socket.disconnect();
                socket = null;
            }
        });

        socket.on('connect_error', (err) => {
            logContainer.innerHTML += `<span class="log-entry log-error">无法连接到服务器: ${err.message}</span>`;
            startBtn.disabled = false;
            startBtn.innerHTML = '<i class="fas fa-broadcast-tower"></i> 启动广播';
        });
    });
}

function initializeMusicControlPage() {
    const pageRoot = document.querySelector('[data-page-id="music_control"]') || document.body;
    const GUILD_ID = document.body.dataset.guildId || pageRoot.dataset.guildId;
    if (!GUILD_ID) return;

    console.log("[Music] Initializing Music Control for Guild:", GUILD_ID);

    // 1. 连接 Socket.IO (定义 socket 变量)
    const socket = io({ transports: ['websocket'], path: '/my-custom-socket-path' });

    // UI 元素引用
    const els = {
        title: document.getElementById('music-title'),
        artist: document.getElementById('music-artist'),
        cover: document.getElementById('music-cover'),
        bg: document.getElementById('player-bg'),
        queue: document.getElementById('queue-container'),
        qCount: document.getElementById('queue-count'),
        volSlider: document.getElementById('vol-slider'),
        volDisplay: document.getElementById('vol-display'),
        searchInput: document.getElementById('search-input'),
        btnSearch: document.getElementById('btn-search'),
        btnSkip: document.getElementById('btn-skip'),
        btnStop: document.getElementById('btn-stop'),
        btnLoop: document.getElementById('btn-loop'),
        loopBadge: document.getElementById('loop-badge'),
        playIcon: document.getElementById('icon-play-state'),
        // 手动加入相关元素
        btnManualJoin: document.getElementById('btn-manual-join'),
        voiceSelect: document.getElementById('manual-voice-select'),
        socketIcon: document.getElementById('socket-status-icon'),
        // 歌单相关元素
        btnSavePlaylist: document.getElementById('btn-save-playlist'),
        playlistModal: document.getElementById('playlistModal'),
        playlistContainer: document.getElementById('playlist-list-container')
    };

    // 辅助函数：发送指令
    const sendCmd = (action, payload = {}) => {
        if (!socket.connected) {
            alert("与服务器的连接已断开，请刷新页面。");
            return;
        }
        socket.emit('music_command', { 
            guild_id: GUILD_ID, 
            action: action, 
            ...payload 
        });
    };

    // 2. Socket 基础连接事件
    socket.on('connect', () => {
        console.log("[Music] Socket Connected");
        if(els.socketIcon) {
            els.socketIcon.style.color = '#00ffaa'; // Green
            els.socketIcon.title = "已连接";
        }
        // 加入房间并请求初始状态
        socket.emit('join_music_room', { guild_id: GUILD_ID });
        sendCmd('get_state');
    });

    socket.on('disconnect', () => {
        console.log("[Music] Socket Disconnected");
        if(els.socketIcon) {
            els.socketIcon.style.color = '#ff5555'; // Red
            els.socketIcon.title = "连接断开";
        }
    });

    // 3. 播放器状态同步处理
    socket.on('music_status_update', (data) => {
        const voiceWarning = data.voice_warning || '';
        const queue = Array.isArray(data.queue) ? data.queue : [];
        if (els.artist) {
            els.artist.title = voiceWarning;
            els.artist.classList.toggle('text-warning', Boolean(voiceWarning));
        }

        // 更新当前歌曲信息
        if (data.current_song) {
            els.title.textContent = data.current_song.title || '未知标题';
            els.artist.textContent = voiceWarning || (data.is_paused ? '已暂停' : (data.current_song.uploader || '未知艺术家'));
            
            const thumbUrl = data.current_song.thumbnail || 'https://cdn.discordapp.com/embed/avatars/0.png';
            if (els.cover.src !== thumbUrl) els.cover.src = thumbUrl;
            els.bg.style.backgroundImage = `url('${thumbUrl}')`;
            
            // 播放状态动画控制
            if (data.is_playing && !voiceWarning) {
                els.cover.classList.add('playing-anim');
                els.playIcon.className = 'fa-solid fa-pause';
            } else {
                els.cover.classList.remove('playing-anim');
                els.playIcon.className = 'fa-solid fa-play';
            }
        } else {
            // 空闲状态
            els.title.textContent = '未在播放';
            els.artist.textContent = voiceWarning || '--';
            els.cover.src = 'https://cdn.discordapp.com/embed/avatars/0.png';
            els.bg.style.backgroundImage = 'none';
            els.cover.classList.remove('playing-anim');
            els.playIcon.className = 'fa-solid fa-play';
        }

        // 更新循环模式徽章
        const loopMap = {'none': 'Off', 'song': '单曲', 'queue': '列表'};
        els.loopBadge.textContent = `Loop: ${loopMap[data.loop_mode] || 'Off'}`;
        els.loopBadge.style.opacity = data.loop_mode === 'none' ? '0' : '1';
        els.loopBadge.className = `position-absolute top-0 start-50 translate-middle badge rounded-pill ${data.loop_mode === 'none' ? 'bg-secondary' : 'bg-success'}`;

        // 更新音量 (防抖动：只有当用户不操作滑块时才更新)
        if (document.activeElement !== els.volSlider) {
            els.volSlider.value = data.volume;
            els.volDisplay.textContent = `${data.volume}%`;
        }

        // 更新播放队列列表
        els.qCount.textContent = `${queue.length} 首歌曲`;
        if (queue.length === 0) {
            els.queue.innerHTML = `
                <div class="text-center text-muted mt-5 pt-5 opacity-50">
                    <i class="fa-solid fa-music fa-4x mb-3"></i>
                    <p>队列空空如也，快去点歌吧！</p>
                </div>`;
        } else {
            // 安全转义函数
            const safe = (str) => {
                if(!str) return '';
                return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
            };

            els.queue.innerHTML = queue.map((song, i) => `
                <div class="queue-item">
                    <span class="me-3 text-secondary font-monospace" style="width:25px;">${i+1}.</span>
                    <div class="flex-grow-1 text-truncate">
                        <div class="text-white fw-bold">${safe(song.title)}</div>
                        <small class="text-muted">${safe(song.uploader)}</small>
                    </div>
                </div>
            `).join('');
        }
    });

    // 4. 加载与错误处理
    socket.on('music_loading', (data) => {
        if(data.status === 'searching') {
            els.searchInput.value = '';
            els.searchInput.placeholder = '🔍 正在搜索并加载...';
            els.btnSearch.disabled = true;
            els.btnSearch.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
        }
    });
    
    socket.on('music_error', (data) => {
        // 恢复搜索按钮状态
        els.searchInput.placeholder = '粘贴链接 (YouTube/SoundCloud) 或输入歌名...';
        els.btnSearch.disabled = false;
        els.btnSearch.innerHTML = '<i class="fa-solid fa-plus me-1"></i> 点歌';
        if (els.btnManualJoin) {
            els.btnManualJoin.disabled = false;
            els.btnManualJoin.innerHTML = '加入';
        }

        if (data.type === 'success') {
            console.log("Success:", data.message);
            if (data.action === 'join' && els.btnManualJoin) {
                els.btnManualJoin.disabled = false;
                els.btnManualJoin.innerHTML = '已加入';
                setTimeout(() => {
                    els.btnManualJoin.innerHTML = '加入';
                }, 1500);
            }
        } else {
            alert("❌ 错误: " + data.message);
        }
    });

    // 5. 播放器按钮事件绑定

    // 点歌
    const handleSearch = () => {
        const query = els.searchInput.value.trim();
        if(!query) return;
        sendCmd('play', { query: query });
    };
    els.btnSearch.addEventListener('click', handleSearch);
    els.searchInput.addEventListener('keypress', (e) => {
        if(e.key === 'Enter') handleSearch();
    });

    // 播放控制
    els.btnSkip.addEventListener('click', () => sendCmd('skip'));
    els.btnStop.addEventListener('click', () => {
        if(confirm("确定要停止播放并清空队列吗？")) sendCmd('stop');
    });
    els.btnLoop.addEventListener('click', () => sendCmd('loop'));

    // 音量调节 (节流)
    let volTimeout;
    els.volSlider.addEventListener('input', (e) => {
        els.volDisplay.textContent = `${e.target.value}%`;
        clearTimeout(volTimeout);
        volTimeout = setTimeout(() => {
            sendCmd('volume', { level: e.target.value });
        }, 300);
    });

    // 手动加入频道
    if (els.btnManualJoin && els.voiceSelect) {
        els.btnManualJoin.addEventListener('click', () => {
            const channelId = els.voiceSelect.value;
            if (!channelId) {
                alert("请先从下拉菜单中选择一个语音频道！");
                return;
            }
            const originalHtml = els.btnManualJoin.innerHTML;
            els.btnManualJoin.disabled = true;
            els.btnManualJoin.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

            sendCmd('join', { target_channel_id: channelId });

            setTimeout(() => {
                els.btnManualJoin.disabled = false;
                els.btnManualJoin.innerHTML = '已发送';
                setTimeout(() => {
                    els.btnManualJoin.innerHTML = originalHtml;
                }, 1200);
            }, 2000);
        });
    }

    // ===============================================
    // ==  ↓↓↓ 歌单系统逻辑 (移到了函数内部) ↓↓↓  ==
    // ===============================================

    // 6. 监听歌单列表更新
    socket.on('playlist_list_update', (data) => {
        const container = els.playlistContainer;
        if (!container) return;

        if (!data.playlists || data.playlists.length === 0) {
            container.innerHTML = '<div class="text-center p-4 text-muted">你还没有创建任何歌单。</div>';
            return;
        }

        container.innerHTML = data.playlists.map(pl => `
            <div class="list-group-item bg-transparent text-white border-secondary d-flex justify-content-between align-items-center">
                <div>
                    <h6 class="mb-0 fw-bold">${escapeHtml(pl.name)}</h6>
                    <small class="text-muted">${pl.track_count} 首歌曲 • ${new Date(pl.created_at * 1000).toLocaleDateString()}</small>
                </div>
                <div class="btn-group">
                    <button class="btn btn-sm btn-success btn-load-pl" data-name="${escapeHtml(pl.name)}" title="加载并播放">
                        <i class="fa-solid fa-play"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger btn-del-pl" data-name="${escapeHtml(pl.name)}" title="删除">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                </div>
            </div>
        `).join('');

        // 绑定动态按钮事件 (加载)
        container.querySelectorAll('.btn-load-pl').forEach(btn => {
            btn.addEventListener('click', () => {
                const plName = btn.dataset.name;
                const targetChannelId = els.voiceSelect ? els.voiceSelect.value : null;
                
                if(confirm(`确定要加载歌单 "${plName}" 吗？这会将歌曲添加到当前队列。`)) {
                    sendCmd('playlist_load', { name: plName, target_channel_id: targetChannelId });
                    // 关闭模态框
                    const modal = bootstrap.Modal.getInstance(els.playlistModal);
                    if(modal) modal.hide();
                }
            });
        });

        // 绑定动态按钮事件 (删除)
        container.querySelectorAll('.btn-del-pl').forEach(btn => {
            btn.addEventListener('click', () => {
                const plName = btn.dataset.name;
                if(confirm(`⚠️ 确定要永久删除歌单 "${plName}" 吗？此操作无法撤销！`)) {
                    sendCmd('playlist_delete', { name: plName });
                }
            });
        });
    });

    // 7. 保存歌单按钮
    if (els.btnSavePlaylist) {
        els.btnSavePlaylist.addEventListener('click', () => {
            const name = prompt("请输入新歌单的名称：");
            if (name) {
                sendCmd('playlist_save', { name: name });
            }
        });
    }

    // 8. 打开歌单模态框时获取列表
    if (els.playlistModal) {
        els.playlistModal.addEventListener('show.bs.modal', () => {
            sendCmd('playlist_list');
        });
    }

} // <--- 函数结束
