<?php if ( ! defined( 'ABSPATH' ) ) exit; get_header(); ?>

<article class="tdf-page">
	<p class="tdf-post-meta">Search results</p>
	<h1 style="margin-top:0">
		<?php if ( have_posts() ) : ?>
			Posts matching &ldquo;<?php echo esc_html( get_search_query() ); ?>&rdquo;
		<?php else : ?>
			No matches for &ldquo;<?php echo esc_html( get_search_query() ); ?>&rdquo;
		<?php endif; ?>
	</h1>

	<form role="search" method="get" class="tdf-search" action="<?php echo esc_url( home_url( '/' ) ); ?>">
		<input type="search" name="s" placeholder="Search posts…" value="<?php echo esc_attr( get_search_query() ); ?>">
		<button type="submit">Search</button>
	</form>
</article>

<?php if ( have_posts() ) : ?>
	<?php while ( have_posts() ) : the_post(); ?>
		<article class="tdf-post">
			<p class="tdf-post-meta">
				<time datetime="<?php echo esc_attr( get_the_date( 'c' ) ); ?>"><?php echo esc_html( get_the_date() ); ?></time>
			</p>
			<h2 style="margin-top:0">
				<a href="<?php the_permalink(); ?>" style="color:var(--fg)"><?php the_title(); ?></a>
			</h2>
			<?php the_excerpt(); ?>
			<a href="<?php the_permalink(); ?>" class="tdf-readmore">Read more &rarr;</a>
		</article>
	<?php endwhile; ?>

	<div class="tdf-pagination">
		<?php echo paginate_links( array( 'prev_text' => '&larr; Newer', 'next_text' => 'Older &rarr;' ) ); ?>
	</div>
<?php endif; ?>

<?php get_footer(); ?>
