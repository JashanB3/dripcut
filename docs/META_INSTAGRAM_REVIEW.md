# Meta Instagram review checklist

DripCut uses Instagram Login so a customer can connect an Instagram Creator or Business account
directly. A Facebook Page is not required.

## Production configuration

- OAuth redirect URI: `https://dripcut.onrender.com/api/social/instagram/callback`
- Deauthorize callback URL: `https://dripcut.onrender.com/api/social/instagram/deauthorize`
- Data deletion request URL: `https://dripcut.onrender.com/api/social/instagram/data-deletion`
- Privacy policy URL: `https://dripcut.onrender.com/privacy`
- Terms URL: `https://dripcut.onrender.com/terms`

Request Advanced Access only for:

- `instagram_business_basic`
- `instagram_business_content_publish`

DripCut does not need messages, comments, insights, or Human Agent permissions for scheduling
Reels.

## Review descriptions

### instagram_business_basic

DripCut uses this permission after a customer clicks **Connect Instagram** and approves access in
Instagram. DripCut reads the selected professional account's identifier and username so it can
show the customer which account is connected and store the connection in the correct private
workspace. DripCut does not use this permission to discover or connect a different account.

### instagram_business_content_publish

DripCut lets a customer turn a video they own or are permitted to use into short clips. The
customer selects the finished clips, chooses Instagram Reels, writes or reviews the caption, and
explicitly confirms **Publish now** or a future schedule. DripCut then uploads only those approved
clips to the connected professional account. The customer can review the queue and disconnect the
account from Settings at any time.

## Screen recording

Use an enrolled Instagram test account and record the complete browser window:

1. Open DripCut Settings while signed into a reviewer-accessible DripCut test account.
2. Click **Connect Instagram**.
3. Show the Instagram consent screen with only profile/basic and content-publishing access.
4. Approve access and show the return to DripCut with the connected Instagram username.
5. Open a completed DripCut project and go to Schedule.
6. Select one finished clip, Instagram Reels, a caption, and **Publish now**.
7. Confirm publishing and show the successful Reel result or permalink.
8. Return to Settings and show the Disconnect control.

Do not include passwords, app secrets, access tokens, or private user data in the recording.
Provide Meta with a dedicated DripCut reviewer account and any Instagram tester instructions only
inside the private review form.
