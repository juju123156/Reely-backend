package com.reely.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;
import java.util.List;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class SpotifyDto {
    private Tracks tracks;

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Tracks {
        private String href;
        private List<Item> items;
        private int limit;
        private String next;
        private int offset;
        private String previous;
        private int total;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Item {
        private String id;
        private String name;
        private List<Artist> artists;
        private Album album;
        @JsonProperty("preview_url")
        private String previewUrl;
        @JsonProperty("duration_ms")
        private int durationMs;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Artist {
        private String id;
        private String name;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Album {
        private String id;
        private String name;
        private List<Image> images;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Image {
        private String url;
        private int height;
        private int width;
    }
} 