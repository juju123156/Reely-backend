package com.reely.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;
import java.util.List;

@Data
public class SpotifyDto {
    private Tracks tracks;

    @Data
    public static class Tracks {
        private List<Item> items;
    }

    @Data
    public static class Item {
        private String id;
        private String name;
        private List<Artist> artists;
        private Album album;
        private String preview_url;
        private int duration_ms;
    }

    @Data
    public static class Artist {
        private String id;
        private String name;
    }

    @Data
    public static class Album {
        private String id;
        private String name;
        private List<Image> images;
    }

    @Data
    public static class Image {
        private String url;
        private int height;
        private int width;
    }
} 