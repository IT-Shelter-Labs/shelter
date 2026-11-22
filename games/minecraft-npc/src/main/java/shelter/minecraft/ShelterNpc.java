package shelter.minecraft;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.HexFormat;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.bukkit.Location;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Husk;
import org.bukkit.entity.Mannequin;
import org.bukkit.entity.Player;
import net.kyori.adventure.text.Component;
import org.bukkit.plugin.java.JavaPlugin;

public final class ShelterNpc extends JavaPlugin {
    private static final int PORT = 27846;
    private static final SecureRandom RANDOM = new SecureRandom();
    private record Pairing(UUID owner, String token) {}
    private volatile Pairing pairing;
    private HttpServer server;
    private Mannequin npc;
    private Husk navigation;
    private String state = "idle";
    private int movementTicks;
    private final AtomicBoolean pending = new AtomicBoolean();

    @Override public void onEnable() {
        if (!getServer().getOnlineMode()) {
            getLogger().warning("Shelter NPC requires an authenticated server (online-mode=true).");
            return;
        }
        try {
            server = HttpServer.create(new InetSocketAddress("127.0.0.1", PORT), 4);
            server.createContext("/npc", this::handle);
            server.start();
            getServer().getScheduler().runTaskTimer(this, this::advance, 10, 10);
            getServer().getScheduler().runTaskTimer(this, this::syncAppearance, 1, 2);
        } catch (IOException e) {
            getLogger().warning("Cannot bind local NPC bridge on port " + PORT + ".");
        }
    }

    @Override public void onDisable() {
        pairing = null;
        if (server != null) server.stop(0);
        removeNpc();
    }

    @Override public boolean onCommand(CommandSender sender, Command command, String alias, String[] args) {
        if (!(sender instanceof Player player) || args.length != 1 || server == null) return false;
        if ("pair".equalsIgnoreCase(args[0])) {
            removeNpc();
            byte[] secret = new byte[32];
            RANDOM.nextBytes(secret);
            Pairing next = new Pairing(player.getUniqueId(), HexFormat.of().formatHex(secret));
            pairing = next;
            // Send only to the authenticated player, never to the server log or global chat.
            player.sendMessage(Component.text("Shelter — copy the pairing code into Jarvis")
                    .clickEvent(net.kyori.adventure.text.event.ClickEvent.copyToClipboard(next.token())));
            return true;
        }
        if ("stop".equalsIgnoreCase(args[0]) && pairing != null && pairing.owner().equals(player.getUniqueId())) {
            pairing = null;
            removeNpc();
            player.sendMessage("Shelter NPC disconnected.");
            return true;
        }
        return false;
    }

    private void handle(HttpExchange exchange) throws IOException {
        try (exchange) {
            Pairing current = pairing;
            String header = exchange.getRequestHeaders().getFirst("Authorization");
            if (current == null || header == null || !MessageDigest.isEqual(
                    ("Bearer " + current.token()).getBytes(StandardCharsets.US_ASCII),
                    header.getBytes(StandardCharsets.US_ASCII))) {
                respond(exchange, 401, "{}");
                return;
            }
            String operation = exchange.getRequestURI().getPath();
            if (!"POST".equals(exchange.getRequestMethod()) || !operation.matches("/npc/(status|spawn|come|follow|stop|remove|say)")) {
                respond(exchange, 404, "{}");
                return;
            }
            if (!pending.compareAndSet(false, true)) {
                respond(exchange, 429, "{}");
                return;
            }
            try {
                String message = "";
                if (operation.endsWith("/say")) {
                    byte[] body = exchange.getRequestBody().readNBytes(1025);
                    if (body.length > 1024) { respond(exchange, 413, "{}"); return; }
                    message = new String(body, StandardCharsets.UTF_8).replaceAll("[\\p{C}§]", " ").strip();
                }
                String speech = message;
                var task = getServer().getScheduler().callSyncMethod(this, () -> {
                    if (pairing != current) return "{\"state\":\"disconnected\"}";
                    return apply(current, operation.substring(5), speech);
                });
                try {
                    respond(exchange, 200, task.get(1200, TimeUnit.MILLISECONDS));
                } catch (Exception e) {
                    task.cancel(false);
                    respond(exchange, 503, "{}");
                }
            } finally {
                pending.set(false);
            }
        }
    }

    private static void respond(HttpExchange exchange, int code, String json) throws IOException {
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(code, bytes.length);
        exchange.getResponseBody().write(bytes);
    }

    private String apply(Pairing current, String operation, String speech) {
        Player player = getServer().getPlayer(current.owner());
        if (player == null) return "{\"state\":\"owner_offline\"}";
        if ("remove".equals(operation)) removeNpc();
        if ("spawn".equals(operation) && (npc == null || !npc.isValid())) {
            removeNpc();
            Location spawn = player.getLocation();
            navigation = player.getWorld().spawn(spawn, Husk.class, entity -> {
                entity.setAdult();
                entity.setInvisible(true);
                entity.setInvulnerable(true);
                entity.setCollidable(false);
                entity.setPersistent(false);
                entity.setRemoveWhenFarAway(false);
                entity.setSilent(true);
                entity.setCanPickupItems(false);
                getServer().getMobGoals().removeAllGoals(entity);
            });
            try {
                npc = player.getWorld().spawn(spawn, Mannequin.class, entity -> {
                    entity.setProfile(Mannequin.defaultProfile());
                    entity.setDescription(Component.text("Shelter"));
                    entity.setPersistent(false);
                    entity.setGravity(false);
                    entity.setInvulnerable(true);
                    entity.setCollidable(false);
                    entity.setSilent(true);
                    entity.setCanPickupItems(false);
                });
            } catch (RuntimeException error) {
                removeNpc();
                throw error;
            }
            state = "ready";
        }
        if (npc == null || !npc.isValid()) return "{\"state\":\"idle\"}";
        if ("say".equals(operation) && !speech.isBlank()) {
            player.sendMessage(Component.text("Shelter: " + speech));
        }
        if ("stop".equals(operation)) stop("stopped");
        if ("follow".equals(operation) || "come".equals(operation)) {
            movementTicks = 0;
            state = operation;
            advance();
        }
        Location pos = navigation.getLocation();
        return String.format(Locale.ROOT, "{\"state\":\"%s\",\"kind\":\"mannequin\",\"x\":%.1f,\"y\":%.1f,\"z\":%.1f}",
                state, pos.getX(), pos.getY(), pos.getZ());
    }

    private void advance() {
        Pairing current = pairing;
        if (current == null) return;
        Player player = getServer().getPlayer(current.owner());
        if (player == null) { removeNpc(); return; }
        if (navigation == null || !navigation.isValid() || !(state.equals("come") || state.equals("follow"))) return;
        if (!navigation.getWorld().equals(player.getWorld())) { stop("different_world"); return; }
        if (++movementTicks > (state.equals("come") ? 60 : 600)) { stop("timeout"); return; }
        Location target = player.getLocation();
        double distance = navigation.getLocation().distanceSquared(target);
        if (distance <= 9) {
            if (state.equals("come")) stop("arrived");
            else navigation.getPathfinder().stopPathfinding();
        } else if (distance > 48 * 48 || !navigation.getPathfinder().moveTo(target, 1.15)) {
            stop("no_path");
        }
    }

    private void syncAppearance() {
        if (npc == null) return;
        if (!npc.isValid() || navigation == null || !navigation.isValid()) {
            removeNpc();
            return;
        }
        Location position = navigation.getLocation();
        if (!position.equals(npc.getLocation())) npc.teleport(position);
    }

    private void stop(String next) {
        if (navigation != null && navigation.isValid()) navigation.getPathfinder().stopPathfinding();
        state = next;
    }

    private void removeNpc() {
        if (npc != null) npc.remove();
        if (navigation != null) navigation.remove();
        npc = null;
        navigation = null;
        state = "idle";
    }
}
