CTFd.plugin.run((_CTFd) => {
    const $ = _CTFd.lib.$
    const md = _CTFd.lib.markdown()
})

function bindReward() {
    btn = document.getElementById("bindRewardBtn");
    fetch('/api/v1/pwnmychall/awards/bind/'+btn.getAttribute("value")).then((data) => data.json()).then((data) => {
        
        if(!data.success) {
            // TODO
            console.log("non bindato")
        }
        if(data.success) {
            // data.data.user.name
            // TODO
            console.log("bindato: ", data.data)
        }
        console.log(data)
    })
}