# Google AdSense Setup Instructions

These steps will get live Google ads running on interstellarsanctuary.com.
The site is already coded to accept AdSense. You only need to complete the
signup, then update one file (ads.json) with your IDs.

---

## Step 1: Sign up for AdSense

1. Go to **adsense.google.com**
2. Sign in with your Google account (use the one you want payments sent to)
3. Click **Get started**
4. Enter the website URL: `interstellarsanctuary.com`
5. Choose your country and accept the terms
6. Click **Start using AdSense**

---

## Step 2: Verify site ownership

After signup, Google will give you a small code snippet that looks like this:

```html
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-XXXXXXXXXXXXXXXX"
     crossorigin="anonymous"></script>
```

Send that snippet to Thomas. He will add it to the site and push it live within minutes.

Google will then verify the site and review it for approval. This usually takes 1 to 3 days.

---

## Step 3: Create your ad units (after approval)

Once Google emails you to say the site is approved:

1. In your AdSense dashboard, go to **Ads** in the left sidebar
2. Click **By ad unit**, then **Create new ad unit**
3. Choose **Display ads**
4. Name it `Sidebar` and set the size to **Responsive**
5. Click **Create**, then copy the `data-ad-slot` number (e.g. `1234567890`)
6. Repeat the same steps to create a second unit named `Top Banner`

You will also need your **Publisher ID**, which is shown at the top of your
AdSense account. It looks like `ca-pub-1234567890123456`.

---

## Step 4: Update ads.json (30 seconds)

In the GitHub repository (`hik113-AI/Live-testing-`), open the file **ads.json**
and replace the entire contents with:

```json
{
  "adsense_client": "ca-pub-XXXXXXXXXXXXXXXX",
  "sidebar": {
    "type": "adsense",
    "slot": "XXXXXXXXXX",
    "format": "auto"
  },
  "top_banner": {
    "type": "adsense",
    "slot": "XXXXXXXXXX",
    "format": "auto"
  }
}
```

Fill in your actual Publisher ID and the two slot numbers, then commit the file.
The site will show live Google ads within a minute of pushing.

---

## Notes

- You can run a direct advertiser deal and AdSense at the same time by mixing
  `"type": "direct"` and `"type": "adsense"` in the two slots independently
- To pause ads on any slot, set that key to `null` in ads.json
- AdSense pays out monthly once your balance reaches RM400 (the Malaysia threshold)
- Thomas can help with any of the technical steps at any point
