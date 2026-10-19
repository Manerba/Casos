/** User management inside the settings panel; fields retain independent drafts. */
let benutzerData = [];
async function initBenutzerTab() {
    await settingsInitSection('benutzer', {loadFn: loadSettingsUsers, renderFn: renderSettingsUsers});
}
async function loadSettingsUsers() { benutzerData = (await settingsRequest('/api/admin/users')).items; }
function renderSettingsUsers() {
    const panel = settingsContainer('benutzer');
    const opened = new Set([...panel.querySelectorAll('details[open]')].map(el => el.dataset.userId));
    let html = `<div class="control-bar"><button class="action-btn primary" id="settingsNewUser">${t('users.newBtn')}</button><input id="settingsUserSearch" placeholder="${escapeAttr(t('common.search'))}" data-settings-transient="true"></div>`;
    for (const user of benutzerData) {
        const ldap = user.auth_source === 'ldap';
        const readonly = ldap ? 'readonly' : '';
        html += `<details data-user-id="${user.id}" ${opened.has(String(user.id)) ? 'open' : ''}><summary>${escapeHtml(user.username)} · ${escapeHtml([user.vorname,user.nachname].filter(Boolean).join(' '))} · ${escapeHtml(user.auth_source)} · ${t(user.is_active ? 'users.active' : 'users.inactive')}</summary><div class="mail-section"><label>${t('users.firstName')}<input id="editVorname_${user.id}" value="${escapeAttr(user.vorname)}" ${readonly}></label><label>${t('users.lastName')}<input id="editNachname_${user.id}" value="${escapeAttr(user.nachname)}" ${readonly}></label><label>${t('users.email')}<input type="email" id="editEmail_${user.id}" value="${escapeAttr(user.email)}" ${readonly}></label><label><input type="checkbox" id="editAdmin_${user.id}" ${user.is_admin ? 'checked' : ''}>${t('users.administrator')}</label><label><input type="checkbox" id="editActive_${user.id}" ${user.is_active ? 'checked' : ''} ${ldap ? 'disabled' : ''}>${t('users.active')}</label>${ldap ? '' : `<label>${t('users.newPasswordHint')}<input type="password" autocomplete="new-password" id="editPassword_${user.id}"></label>`}<button class="action-btn primary" data-save-user="${user.id}">${t('common.save')}</button> ${user.email ? `<button class="action-btn" data-invite-user="${user.id}">${t('users.sendInvite')}</button>` : ''} ${!ldap || !user.is_active ? `<button class="action-btn danger" data-delete-user="${user.id}">${t('common.delete')}</button>` : ''}</div></details>`;
    }
    settingsRender('benutzer', html);
    settingsField('benutzer','settingsNewUser').onclick = openNewUserModal;
    settingsField('benutzer','settingsUserSearch').oninput = event => {
        const search = event.target.value.toLocaleLowerCase();
        panel.querySelectorAll('details').forEach(element => { element.hidden = !element.textContent.toLocaleLowerCase().includes(search); });
    };
    panel.querySelectorAll('[data-save-user]').forEach(button => { button.onclick = () => saveUser(Number(button.dataset.saveUser)); });
    panel.querySelectorAll('[data-delete-user]').forEach(button => { button.onclick = () => deleteUser(Number(button.dataset.deleteUser)); });
    panel.querySelectorAll('[data-invite-user]').forEach(button => { button.onclick = () => sendInviteMail(Number(button.dataset.inviteUser)); });
}
async function saveUser(userId) {
    return settingsAction(async () => {
    const row = benutzerData.find(user => user.id === userId);
    const body = {is_admin: settingsField('benutzer', `editAdmin_${userId}`).checked ? 1 : 0};
    if (row.auth_source !== 'ldap') {
        for (const [field,prefix] of [['vorname','Vorname'],['nachname','Nachname'],['email','Email']]) body[field] = settingsField('benutzer', `edit${prefix}_${userId}`).value;
        body.is_active = settingsField('benutzer', `editActive_${userId}`).checked ? 1 : 0;
        const password = settingsField('benutzer', `editPassword_${userId}`).value;
        if (password) body.password = password;
    }
    try {
        await settingsRequest(`/api/admin/users/${userId}`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        settingsMarkSaved('benutzer', ['Vorname','Nachname','Email','Admin','Active','Password'].map(part => `edit${part}_${userId}`));
        await loadSettingsUsers(); renderSettingsUsers();
        settingsNotify(t('users.saved'),'success');
    } catch(error) { settingsNotify(error.message,'error'); }
    });
}
async function deleteUser(userId) {
    return settingsAction(async () => {
    const username = benutzerData.find(user => user.id === userId)?.username || '';
    if (!await settingsConfirm(t('users.deleteConfirm',{username}))) return;
    try {
        await settingsRequest(`/api/admin/users/${userId}`, {method:'DELETE'});
        await loadSettingsUsers(); renderSettingsUsers();
        settingsNotify(t('users.deleted'),'success');
    } catch(error) { settingsNotify(error.message,'error'); }
    });
}
function openNewUserModal() {
    const fields = [['newUsername','users.usernameRequired','text'],['newVorname','users.firstName','text'],['newNachname','users.lastName','text'],['newEmail','users.email','email'],['newPassword','users.passwordRequired','password']];
    settingsCreateModal({title:t('users.new'),body:fields.map(([id,key,type])=>`<label>${t(key)}<input id="${id}" type="${type}" autocomplete="${type==='password'?'new-password':'off'}"></label>`).join('')+`<label><input type="checkbox" id="newIsAdmin">${t('users.administrator')}</label>`,footer:`<button class="action-btn" onclick="settingsCloseModal()">${t('common.cancel')}</button><button class="action-btn primary" id="createUserBtn">${t('common.create')}</button>`,onOpen:overlay=>{
        overlay.querySelector('#createUserBtn').onclick=()=>settingsAction(async()=>{
            const body={};
            for(const [field,id] of [['username','newUsername'],['vorname','newVorname'],['nachname','newNachname'],['email','newEmail'],['password','newPassword']]) body[field]=overlay.querySelector('#'+id).value;
            body.is_admin=overlay.querySelector('#newIsAdmin').checked?1:0;
            try {
                await settingsRequest('/api/admin/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
                await settingsCloseModal(true);
                await loadSettingsUsers(); renderSettingsUsers();
                settingsNotify(t('users.createdMsg'),'success');
            }catch(error){settingsNotify(error.message,'error');}
        });
    }});
}
async function sendInviteMail(userId) {
    return settingsAction(async () => {
    const username=benutzerData.find(user=>user.id===userId)?.username||'';
    if(!await settingsConfirm(t('users.inviteConfirm',{username}))) return;
    try { await settingsRequest(`/api/admin/mail/invite/${userId}`,{method:'POST'}); settingsNotify(t('users.inviteSent'),'success'); }
    catch(error){settingsNotify(error.message,'error');}
    });
}
