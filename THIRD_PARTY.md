# Third-party data

## Cargo grids: sc-cargo.space

Pledge Watch downloads cargo grid data from https://github.com/sccargospace/sc-cargo.space and serves it on the
website and in `/ships.json`. That data is used under the MIT licence:

```
MIT License

Copyright (c) 2026 sccargospace

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Star Citizen Wiki API

Insurance claim and expedite times, pledge price history, stock weapons, each ship's release patch (`addedinversion` on the
wiki's ship pages) and the list of gold standard ships (the wiki's Vehicle Pipeline page) come from https://api.star-citizen.wiki (the Star
Citizen Wiki, https://starcitizen.tools). Wiki content is licensed CC BY-SA 4.0
(https://creativecommons.org/licenses/by-sa/4.0/); Pledge Watch credits it on the site and passes those figures on
under the same terms in `/ships.json`.

## scunpacked-data

For turrets the wiki API's turret list leaves out, whether the pilot can slave the turret (`IsPilotSlaveable`) is read
from the ship files in https://github.com/StarCitizenWiki/scunpacked-data, the Star Citizen Wiki team's dump of the
game files (made with https://github.com/octfx/ScDataDumper). The repository doesn't state a licence; Pledge Watch uses
that one flag, credits the source on the site, and doesn't redistribute the files. The underlying game data belongs to
Cloud Imperium Games.

## UEX

In-game buy and rent prices come from the public UEX API (https://uexcorp.space), credited on the site.

## RSI

Ship, store and loaner data come from Roberts Space Industries' public website. Pledge Watch is a fan project and is
not affiliated with Cloud Imperium Games or Roberts Space Industries.
